from __future__ import annotations

from pathlib import Path
import re
import subprocess
import time

from PySide6.QtWidgets import QCheckBox, QGridLayout, QLabel

from . import browser_ai, browser_sessions, pipeline, services, ui, v070_voice, v114_json_capture


_PREVIOUS_PIPELINE_RUN = pipeline.Pipeline.run
_PREVIOUS_CREATE_PAGE = ui.MainWindow._create_page
_PREVIOUS_MAKE_PROJECT = ui.MainWindow._make_project
_PREVIOUS_SCENE_CLIPS = services.FFmpegRenderer._render_scene_clips
_PREVIOUS_RENDER = services.FFmpegRenderer.render


# ---------------------------------------------------------------------------
# ChatGPT conversation reuse
# ---------------------------------------------------------------------------

def _saved_chat_url() -> str:
    try:
        state = browser_sessions._load_state().get("chatgpt") or {}
        value = str(state.get("last_chat_url") or "")
        return value if re.match(r"^https://chatgpt\.com/c/[A-Za-z0-9_-]+", value) else ""
    except Exception:
        return ""


def _remember_chat_url(client) -> str:
    try:
        value = str(client.page.url or "")
    except Exception:
        return ""
    if re.match(r"^https://chatgpt\.com/c/[A-Za-z0-9_-]+", value):
        browser_ai._thread.chat_url = value
        try:
            browser_sessions.update_state("chatgpt", last_chat_url=value)
        except Exception:
            pass
        return value
    return ""


def _configure_chat_session(new_chat: bool) -> None:
    browser_ai._thread.chat_new_requested = bool(new_chat)
    browser_ai._thread.chat_context_ready = False
    browser_ai._thread.chat_url = "" if new_chat else _saved_chat_url()


def _ensure_chat_context(client) -> None:
    client.open()
    ready = bool(getattr(browser_ai._thread, "chat_context_ready", False))
    chat_url = str(getattr(browser_ai._thread, "chat_url", "") or "")

    # After the ChatGPT -> ElevenLabs lifecycle handoff, Playwright is intentionally
    # restarted. Return to the reel's remembered conversation instead of silently
    # opening a fresh chat.
    if ready:
        if chat_url and client.page.url != chat_url:
            client.page.goto(chat_url, wait_until="domcontentloaded", timeout=45000)
            client._ensure_ready()
        return

    if bool(getattr(browser_ai._thread, "chat_new_requested", False)):
        # "New Chat" means one new conversation for the reel, NOT a new chat for every
        # script/tag/image request. Later requests reuse the conversation URL created here.
        client.new_chat()
    elif chat_url and client.page.url != chat_url:
        client.page.goto(chat_url, wait_until="domcontentloaded", timeout=45000)
        client._ensure_ready()

    browser_ai._thread.chat_context_ready = True
    _remember_chat_url(client)


def _ask_json_reuse(self, prompt: str, *, timeout_ms: int = 180000) -> dict:
    _ensure_chat_context(self)
    baseline_fps = v114_json_capture._json_fingerprints(v114_json_capture._body_text(self.page))
    self._fill_and_send(prompt)
    value = v114_json_capture._wait_json_v114(self, baseline_fps, prompt, timeout_ms)
    _remember_chat_url(self)
    return value


def _generate_image_reuse(self, prompt: str, out_base: Path, *, timeout_ms: int = 360000) -> Path:
    _ensure_chat_context(self)
    try:
        baseline_sources = set(
            self.page.locator("img").evaluate_all("imgs => imgs.map(i => i.currentSrc || i.src).filter(Boolean)")
        )
    except Exception:
        baseline_sources = set()

    self.image_candidates = []
    self._generation_started = time.time()
    request = (
        "Generate the image now. Do not just describe it. Create one polished visual for a short-form video.\n\n"
        + prompt
        + "\n\nNo captions, no visible UI, no watermark, no logo, and avoid accidental readable text unless specifically required."
    )

    started = time.time()
    deadline = started + max(60.0, timeout_ms / 1000.0)
    candidate_since: float | None = None
    next_dom_probe = started + 10.0
    last_body = ""
    try:
        self._fill_and_send(request)
        while time.time() < deadline:
            v114_json_capture._human_gate(self.page)
            _remember_chat_url(self)
            now = time.time()
            if self.image_candidates:
                best = self.image_candidates[0]
                if candidate_since is None:
                    candidate_since = now
                if not v114_json_capture._stop_visible(self.page) or now - candidate_since >= 4.0:
                    return v114_json_capture._save_image_candidate(out_base, best)

            if now >= next_dom_probe:
                dom = self._dom_image_bytes(self.page.locator("body"), baseline_sources)
                if dom:
                    raw, ext = dom
                    target = out_base.with_suffix(ext)
                    target.parent.mkdir(parents=True, exist_ok=True)
                    target.write_bytes(raw)
                    return target
                last_body = v114_json_capture._body_text(self.page, limit=40_000)
                next_dom_probe = now + 3.0
            time.sleep(0.4)
    finally:
        self._generation_started = 0.0
        _remember_chat_url(self)

    tail = v114_json_capture._norm(last_body or v114_json_capture._body_text(self.page, limit=40_000))[-700:]
    raise RuntimeError(
        "ChatGPT did not expose a generated image before the browser timeout. "
        f"Current page: {self.page.url}. Visible page tail: {tail or 'no readable page text'}"
    )


# ---------------------------------------------------------------------------
# ElevenLabs: insert and verify the ENTIRE performance script
# ---------------------------------------------------------------------------

def _editor_text(editor) -> str:
    try:
        return str(
            editor.evaluate(
                "el => (typeof el.value === 'string' ? el.value : (el.innerText || el.textContent || ''))"
            )
            or ""
        )
    except Exception:
        return ""


def _spoken_signature(text: str) -> list[str]:
    return browser_ai._tagless_words(text)


def _eleven_script_complete(expected: str, actual: str) -> bool:
    expected_words = _spoken_signature(expected)
    actual_words = _spoken_signature(actual)
    if not expected_words or expected_words != actual_words:
        return False
    # Also require the end of the script to be present. This catches editors that report
    # duplicated/virtualized text oddly while only accepting the first paragraph.
    expected_tail = " ".join(expected_words[-10:])
    actual_text = " ".join(actual_words)
    return not expected_tail or actual_text.endswith(expected_tail)


def _best_eleven_editor(client):
    selectors = [
        '[contenteditable="true"].ProseMirror',
        '[contenteditable="true"][role="textbox"]',
        'textarea[placeholder*="text" i]',
        'textarea[placeholder*="speech" i]',
        "textarea",
        '[contenteditable="true"]',
    ]
    candidates = []
    for selector in selectors:
        locator = client.page.locator(f"{selector}:visible")
        try:
            count = locator.count()
        except Exception:
            continue
        for index in range(min(count, 12)):
            item = locator.nth(index)
            try:
                box = item.bounding_box()
                if not box:
                    continue
                area = float(box.get("width", 0)) * float(box.get("height", 0))
                if area < 20_000:
                    continue
                candidates.append((area, -selectors.index(selector), item))
            except Exception:
                continue
    if not candidates:
        return client._editor()
    candidates.sort(key=lambda row: (row[0], row[1]), reverse=True)
    return candidates[0][2]


def _insert_full_eleven_script(client, text: str):
    editor = _best_eleven_editor(client)
    editor.wait_for(state="visible", timeout=20000)

    def verify() -> bool:
        client.page.wait_for_timeout(350)
        return _eleven_script_complete(text, _editor_text(editor))

    # First choice: real keyboard insertion. Rich text editors (Lexical/ProseMirror) are
    # much more reliable with one insertText operation than locator.fill/press_sequentially.
    try:
        editor.click()
        editor.press("Control+A")
        editor.press("Backspace")
        client.page.keyboard.insert_text(text)
        if verify():
            return editor
    except Exception:
        pass

    # Native textarea fallback.
    try:
        editor.fill(text)
        if verify():
            return editor
    except Exception:
        pass

    # Contenteditable fallback that emits the input/change events used by React editors.
    try:
        editor.evaluate(
            """
            (el, value) => {
              el.focus();
              const selection = window.getSelection();
              if (selection) {
                selection.removeAllRanges();
                const range = document.createRange();
                range.selectNodeContents(el);
                selection.addRange(range);
              }
              document.execCommand('delete', false, null);
              document.execCommand('insertText', false, value);
              el.dispatchEvent(new InputEvent('input', {bubbles:true, inputType:'insertText', data:value}));
              el.dispatchEvent(new Event('change', {bubbles:true}));
            }
            """,
            text,
        )
        if verify():
            return editor
    except Exception:
        pass

    expected = len(_spoken_signature(text))
    actual = len(_spoken_signature(_editor_text(editor)))
    raise RuntimeError(
        "ElevenLabs did not accept the complete narration. "
        f"ZeroReels expected {expected} spoken words but the browser editor contains {actual}. "
        "Generation stopped before spending a TTS generation or creating a shortened video."
    )


def _eleven_render_verified(self, text: str, out_dir: Path, *, timeout_ms: int = 240000) -> Path:
    self.open()
    if "/speech-synthesis" not in self.page.url:
        self.page.goto(self.URL, wait_until="domcontentloaded", timeout=45000)

    _insert_full_eleven_script(self, text)

    button = self._generate_button()
    button.wait_for(state="visible", timeout=15000)
    self.audio_candidates = []
    self._capture = True
    button.click(timeout=15000)
    deadline = time.time() + timeout_ms / 1000
    while time.time() < deadline:
        if self.audio_candidates:
            break
        time.sleep(0.5)
    self._capture = False

    out_dir.mkdir(parents=True, exist_ok=True)
    if self.audio_candidates:
        best = self.audio_candidates[0]
        target = out_dir / f"elevenlabs_browser{best['ext']}"
        target.write_bytes(best["body"])
        return target

    download_button = self.page.locator(
        'button[aria-label*="download" i]:visible,button[title*="download" i]:visible,button:visible:has-text("Download")'
    ).first
    try:
        download_button.wait_for(state="visible", timeout=15000)
        try:
            with self.page.expect_download(timeout=15000) as info:
                download_button.click()
            download = info.value
        except Exception:
            download_button.click()
            mp3 = self.page.get_by_text(re.compile(r"MP3", re.I)).first
            with self.page.expect_download(timeout=15000) as info:
                mp3.click()
            download = info.value
        suffix = Path(download.suggested_filename or "narration.mp3").suffix or ".mp3"
        target = out_dir / f"elevenlabs_browser{suffix}"
        download.save_as(str(target))
        return target
    except Exception as exc:
        raise RuntimeError(
            "ElevenLabs finished without a capturable audio file. Keep the Text to Speech page open in the saved profile and retry. "
            + str(exc)
        ) from exc


def _minimum_plausible_narration_seconds(spoken_words: int) -> float:
    # 300 WPM is already extremely fast. Anything materially shorter almost certainly
    # means ElevenLabs received only part of the intended script.
    return max(2.0, spoken_words / 5.0)


def _voice_generate_verified(self, project, out_dir: Path, progress=None) -> Path:
    tagged = browser_ai.build_elevenlabs_script(project, progress=progress)
    if not tagged:
        raise RuntimeError("Narration is empty.")
    text = "\n\n[pause]\n\n".join(tagged)
    if project.output_dir:
        try:
            Path(project.output_dir, "elevenlabs_script.txt").write_text(
                "\n\n".join(f"Scene {i + 1}:\n{value}" for i, value in enumerate(tagged)), encoding="utf-8"
            )
        except Exception:
            pass
    if progress:
        progress(20, f"ElevenLabs browser • pasting and verifying full script ({len(_spoken_signature(text))} spoken words)")
    source = browser_ai.get_eleven_client().render(text, out_dir, timeout_ms=300000)
    target = out_dir / "narration.wav"
    if source.suffix.lower() == ".wav":
        target.write_bytes(source.read_bytes())
    else:
        proc = subprocess.run(
            [browser_ai._ffmpeg(self.settings), "-y", "-i", str(source), "-ac", "1", "-ar", "44100", "-c:a", "pcm_s16le", str(target)],
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
        )
        if proc.returncode != 0:
            raise RuntimeError(
                "Could not convert ElevenLabs browser audio to WAV: "
                + proc.stderr.decode("utf-8", errors="replace")[-1200:]
            )

    duration = v070_voice._wav_duration(target)
    spoken_words = len(_spoken_signature(text))
    minimum = _minimum_plausible_narration_seconds(spoken_words)
    if spoken_words >= 20 and duration < minimum:
        try:
            target.unlink(missing_ok=True)
        except Exception:
            pass
        raise RuntimeError(
            f"ElevenLabs returned only {duration:.1f}s of audio for {spoken_words} spoken words. "
            f"A complete read should be at least about {minimum:.1f}s even at very fast speech. "
            "ZeroReels stopped before scene timing/render because the TTS result appears truncated."
        )

    v070_voice.apply_scene_timing(project, duration, self.delivery)
    project.actual_seconds = round(duration, 2)
    project.voice_engine_used = browser_ai.ELEVEN_BROWSER_ENGINE
    project.voice_delivery = self.delivery
    if progress:
        progress(29, f"ElevenLabs browser narration verified • {spoken_words} words • {duration:.1f}s")
    return target


# ---------------------------------------------------------------------------
# Renderer integrity: every scene must become one clip and final duration must agree
# ---------------------------------------------------------------------------

def _verify_clip_set(project, clips: list[Path]) -> list[Path]:
    expected = len(project.scenes)
    if len(clips) != expected:
        raise RuntimeError(f"Render integrity check failed: prepared {len(clips)}/{expected} scene clips.")
    bad = []
    for scene, clip in zip(project.scenes, clips):
        path = Path(clip)
        if not path.exists() or path.stat().st_size < 5_000:
            bad.append(scene.index)
    if bad:
        raise RuntimeError("Render integrity check failed for scene clip(s): " + ", ".join(map(str, bad)))
    return clips


def _scene_clips_verified(self, project, out_dir: Path, motion: bool, transitions: bool):
    missing_media = [scene.index for scene in project.scenes if not scene.image_path or not Path(scene.image_path).exists()]
    if missing_media:
        raise RuntimeError("Cannot render: missing visual media for scene(s): " + ", ".join(map(str, missing_media)))
    clips = _PREVIOUS_SCENE_CLIPS(self, project, out_dir, motion, transitions)
    return _verify_clip_set(project, [Path(path) for path in clips])


def _probe_duration(ffmpeg: str, path: Path) -> float:
    proc = subprocess.run([ffmpeg, "-i", str(path)], stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    text = proc.stderr.decode("utf-8", errors="replace")
    match = re.search(r"Duration:\s*(\d+):(\d+):(\d+(?:\.\d+)?)", text)
    if not match:
        return 0.0
    return int(match.group(1)) * 3600 + int(match.group(2)) * 60 + float(match.group(3))


def _render_verified(self, project, audio, captions, out_dir, *args, **kwargs):
    result = _PREVIOUS_RENDER(self, project, audio, captions, out_dir, *args, **kwargs)
    video, burned = result
    video_path = Path(video)
    final_seconds = _probe_duration(self._ffmpeg(), video_path)
    expected_seconds = sum(max(0.0, float(scene.duration)) for scene in project.scenes)
    # Crossfades can shorten the visual program slightly, but never remotely enough to turn
    # a 60-second reel into a 6.8-second file. Refuse to call a truncated movie successful.
    if expected_seconds >= 4 and final_seconds and final_seconds < expected_seconds * 0.72:
        try:
            video_path.rename(video_path.with_name("final_INCOMPLETE.mp4"))
        except Exception:
            pass
        raise RuntimeError(
            f"Render integrity check failed: final movie is {final_seconds:.1f}s but the prepared scene timeline is "
            f"{expected_seconds:.1f}s across {len(project.scenes)} scenes. The incomplete output was not accepted as final.mp4."
        )

    try:
        manifest = Path(out_dir) / "RENDER_MANIFEST.txt"
        lines = [
            f"ZeroReels render integrity: {len(project.scenes)}/{len(project.scenes)} scenes prepared",
            f"Scene timeline: {expected_seconds:.2f}s",
            f"Final movie: {final_seconds:.2f}s" if final_seconds else "Final movie: duration probe unavailable",
            "",
        ]
        for scene in project.scenes:
            lines.append(
                f"{scene.index:03d} | {scene.duration:.3f}s | {scene.media_type or 'image'} | {Path(scene.image_path).name}"
            )
        manifest.write_text("\n".join(lines) + "\n", encoding="utf-8")
    except Exception:
        pass
    return video, burned


# ---------------------------------------------------------------------------
# UI + pipeline integration
# ---------------------------------------------------------------------------

def _create_page_v116(self):
    page = _PREVIOUS_CREATE_PAGE(self)
    if hasattr(self, "script_mode_box"):
        parent = self.script_mode_box.parentWidget()
        layout = parent.layout() if parent else None
        if isinstance(layout, QGridLayout):
            row = layout.rowCount()
            self.chatgpt_new_chat_check = QCheckBox("New Chat for this reel")
            self.chatgpt_new_chat_check.setChecked(False)
            self.chatgpt_new_chat_check.setToolTip(
                "Off: reuse the last ZeroReels ChatGPT conversation. On: start one fresh ChatGPT chat for this reel, then reuse it for script, performance tags, and images."
            )
            layout.addWidget(self.chatgpt_new_chat_check, row, 0, 1, 2)
            hint = QLabel("Unchecked reuses the existing ZeroReels ChatGPT conversation instead of creating a new chat for every browser task.")
            hint.setObjectName("Hint")
            hint.setWordWrap(True)
            layout.addWidget(hint, row + 1, 0, 1, 2)
    return page


def _make_project_v116(self):
    project = _PREVIOUS_MAKE_PROJECT(self)
    project.chatgpt_new_chat = bool(
        self.chatgpt_new_chat_check.isChecked() if hasattr(self, "chatgpt_new_chat_check") else False
    )
    return project


def _pipeline_run_v116(self, project, options, progress=lambda value, text: None):
    _configure_chat_session(bool(getattr(project, "chatgpt_new_chat", False)))
    mode = "new reel chat" if getattr(project, "chatgpt_new_chat", False) else "reuse existing chat"
    try:
        progress(1, f"ChatGPT conversation • {mode}")
    except Exception:
        pass
    return _PREVIOUS_PIPELINE_RUN(self, project, options, progress)


def install() -> None:
    browser_ai.ChatGPTBrowserClient.ask_json = _ask_json_reuse
    browser_ai.ChatGPTBrowserClient.generate_image = _generate_image_reuse
    browser_ai.ElevenLabsBrowserClient.render = _eleven_render_verified
    browser_ai.ElevenLabsBrowserVoiceService.generate = _voice_generate_verified

    services.FFmpegRenderer._render_scene_clips = _scene_clips_verified
    services.FFmpegRenderer.render = _render_verified
    pipeline.Pipeline.run = _pipeline_run_v116

    ui.MainWindow._create_page = _create_page_v116
    ui.MainWindow._make_project = _make_project_v116

    previous_sidebar = ui.MainWindow._sidebar

    def sidebar_v116(self):
        frame = previous_sidebar(self)
        for label in frame.findChildren(QLabel):
            if label.text().startswith("v0."):
                label.setText("v0.11.6 BROWSER")
                label.setMaximumWidth(152)
                break
        return frame

    ui.MainWindow._sidebar = sidebar_v116
