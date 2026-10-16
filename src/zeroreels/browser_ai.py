from __future__ import annotations

from pathlib import Path
import base64
import json
import re
import subprocess
import threading
import time

from . import services, v070_voice
from .browser_sessions import ChromeSession, detect_auth
from .config import find_executable
from .models import Scene


CHATGPT_IMAGE_SOURCE = "ChatGPT Images (Browser)"
ELEVEN_BROWSER_ENGINE = "ElevenLabs Browser"
_thread = threading.local()


def _clean(value: str) -> str:
    return " ".join((value or "").split()).strip()


def _words(text: str) -> list[str]:
    return re.findall(r"[A-Za-z0-9][A-Za-z0-9'’-]*", text or "")


def _extract_json_object(text: str) -> dict:
    value = (text or "").strip()
    value = re.sub(r"^```(?:json)?\s*", "", value, flags=re.IGNORECASE)
    value = re.sub(r"\s*```$", "", value)
    try:
        return json.loads(value)
    except Exception:
        start = value.find("{")
        end = value.rfind("}")
        if start >= 0 and end > start:
            return json.loads(value[start : end + 1])
        raise RuntimeError("ChatGPT browser response did not contain valid JSON.")


def _image_info(body: bytes, content_type: str = "") -> tuple[str, int, int] | None:
    if len(body) >= 24 and body[:8] == b"\x89PNG\r\n\x1a\n":
        return ".png", int.from_bytes(body[16:20], "big"), int.from_bytes(body[20:24], "big")
    if len(body) >= 4 and body[:3] == b"\xff\xd8\xff":
        i = 2
        while i + 9 < len(body):
            if body[i] != 0xFF:
                i += 1
                continue
            marker = body[i + 1]
            if marker in {0xC0, 0xC1, 0xC2, 0xC3, 0xC5, 0xC6, 0xC7, 0xC9, 0xCA, 0xCB, 0xCD, 0xCE, 0xCF}:
                return ".jpg", int.from_bytes(body[i + 5:i + 7], "big"), int.from_bytes(body[i + 7:i + 9], "big")
            if i + 4 >= len(body):
                break
            length = int.from_bytes(body[i + 2:i + 4], "big")
            i += max(2, length + 2)
        return ".jpg", 0, 0
    if len(body) >= 16 and body[:4] == b"RIFF" and body[8:12] == b"WEBP":
        return ".webp", 0, 0
    if "image/png" in content_type.lower():
        return ".png", 0, 0
    if "image/jpeg" in content_type.lower() or "image/jpg" in content_type.lower():
        return ".jpg", 0, 0
    if "image/webp" in content_type.lower():
        return ".webp", 0, 0
    return None


def _audio_ext(body: bytes, content_type: str = "") -> str | None:
    low = content_type.lower()
    if body.startswith(b"RIFF"):
        return ".wav"
    if body.startswith(b"ID3") or (len(body) > 2 and body[0] == 0xFF and body[1] & 0xE0 == 0xE0):
        return ".mp3"
    if body.startswith(b"OggS"):
        return ".ogg"
    if body.startswith(b"fLaC"):
        return ".flac"
    if len(body) > 12 and body[4:8] == b"ftyp":
        return ".m4a"
    if "mpeg" in low or "mp3" in low:
        return ".mp3"
    if "wav" in low:
        return ".wav"
    if "ogg" in low:
        return ".ogg"
    return None


class ChatGPTBrowserClient:
    COMPOSERS = [
        "#prompt-textarea",
        '[data-testid="composer-text-input"]',
        'textarea[placeholder*="Message" i]',
        "textarea",
        '[contenteditable="true"][data-placeholder]',
        '[contenteditable="true"]',
    ]

    def __init__(self):
        self.session: ChromeSession | None = None
        self.page = None
        self.image_candidates: list[dict] = []
        self._observer_installed = False
        self._generation_started = 0.0

    def open(self):
        if self.session and self.page and not self.page.is_closed():
            return self
        self.session = ChromeSession("chatgpt", background=True).start()
        self.page = self.session.page
        self._ensure_ready()
        self._install_image_observer()
        return self

    def close(self):
        if self.session:
            self.session.close()
        self.session = None
        self.page = None

    def _ensure_ready(self):
        page = self.page
        if not page.url.startswith("https://chatgpt.com"):
            page.goto("https://chatgpt.com/", wait_until="domcontentloaded", timeout=45000)
        status, message = detect_auth("chatgpt", page)
        if status != "verified":
            raise RuntimeError(message)
        self._composer().wait_for(state="visible", timeout=15000)

    def _composer(self):
        return self.page.locator(",".join(f"{s}:visible" for s in self.COMPOSERS)).first

    def _assistant_messages(self):
        return self.page.locator('[data-message-author-role="assistant"]')

    def new_chat(self):
        self.open()
        self.page.goto("https://chatgpt.com/", wait_until="domcontentloaded", timeout=45000)
        self._ensure_ready()

    def _fill_and_send(self, prompt: str):
        composer = self._composer()
        composer.wait_for(state="visible", timeout=12000)
        composer.click()
        try:
            composer.fill(prompt)
        except Exception:
            composer.press_sequentially(prompt, delay=1)
        send = self.page.locator(
            'button[data-testid="send-button"]:visible,button[data-testid*="send" i]:visible,button[aria-label*="send" i]:visible'
        ).first
        try:
            send.wait_for(state="visible", timeout=10000)
            send.click(timeout=10000)
        except Exception:
            composer.press("Enter")

    def _wait_response(self, baseline: int, timeout_ms: int = 180000):
        deadline = time.time() + timeout_ms / 1000
        newest = None
        while time.time() < deadline:
            messages = self._assistant_messages()
            count = messages.count()
            if count > baseline:
                newest = messages.nth(count - 1)
                break
            time.sleep(0.5)
        if newest is None:
            raise RuntimeError("ChatGPT did not create a new response.")

        last = ""
        stable_since = time.time()
        while time.time() < deadline:
            try:
                text = newest.inner_text(timeout=3000).strip()
            except Exception:
                text = ""
            stop_visible = False
            try:
                stop_visible = self.page.locator('button[data-testid="stop-button"]:visible,button[aria-label*="stop" i]:visible').count() > 0
            except Exception:
                pass
            if text != last:
                last = text
                stable_since = time.time()
            elif text and not stop_visible and time.time() - stable_since >= 2.5:
                return newest, text
            time.sleep(0.6)
        if last:
            return newest, last
        raise RuntimeError("ChatGPT response did not finish.")

    def ask_text(self, prompt: str, *, new_chat: bool = True, timeout_ms: int = 180000) -> str:
        self.open()
        if new_chat:
            self.new_chat()
        baseline = self._assistant_messages().count()
        self._fill_and_send(prompt)
        _, text = self._wait_response(baseline, timeout_ms)
        return text

    def ask_json(self, prompt: str, *, timeout_ms: int = 180000) -> dict:
        return _extract_json_object(self.ask_text(prompt, new_chat=True, timeout_ms=timeout_ms))

    def _install_image_observer(self):
        if self._observer_installed:
            return

        def on_response(response):
            try:
                if not self._generation_started:
                    return
                url = response.url
                headers = response.headers
                content_type = headers.get("content-type", "")
                likely = content_type.lower().startswith("image/") or re.search(
                    r"oaiusercontent\.com|backend-api.*(?:file|image)|imagegen|dall|generated", url, re.I
                )
                if not likely or not (200 <= response.status < 300):
                    return
                body = response.body()
                if not body or len(body) < 50000:
                    return
                info = _image_info(body, content_type)
                if not info:
                    return
                ext, width, height = info
                score = min(len(body) / 1000, 6000)
                if re.search(r"oaiusercontent\.com|imagegen|dall|generated|file", url, re.I):
                    score += 12000
                if width >= 768 and height >= 768:
                    score += 7000
                self.image_candidates.append({"body": body, "ext": ext, "width": width, "height": height, "score": score, "url": url})
                self.image_candidates.sort(key=lambda x: x["score"], reverse=True)
                del self.image_candidates[12:]
            except Exception:
                pass

        self.page.on("response", on_response)
        self._observer_installed = True

    def _dom_image_bytes(self, message, baseline_sources: set[str]) -> tuple[bytes, str] | None:
        try:
            images = message.locator("img")
            count = images.count()
        except Exception:
            return None
        candidates: list[tuple[int, str]] = []
        for i in range(count):
            img = images.nth(i)
            try:
                data = img.evaluate(
                    "el => ({src: el.currentSrc || el.src || '', w: el.naturalWidth || el.width || 0, h: el.naturalHeight || el.height || 0, alt: el.alt || ''})"
                )
                src = data.get("src", "")
                if not src or src in baseline_sources:
                    continue
                score = int(data.get("w", 0)) * int(data.get("h", 0))
                if re.search(r"generated|imagegen|oaiusercontent|blob:", f"{src} {data.get('alt','')}", re.I):
                    score += 5_000_000
                candidates.append((score, src))
            except Exception:
                continue
        for _, src in sorted(candidates, reverse=True):
            try:
                if src.startswith("data:image/"):
                    header, encoded = src.split(",", 1)
                    raw = base64.b64decode(encoded) if ";base64" in header else encoded.encode()
                    info = _image_info(raw, header)
                    if info and len(raw) > 8192:
                        return raw, info[0]
                if src.startswith("blob:"):
                    encoded = self.page.evaluate(
                        """async src => { const r=await fetch(src); const b=new Uint8Array(await r.arrayBuffer()); let s=''; for(let i=0;i<b.length;i+=32768){s+=String.fromCharCode(...b.subarray(i,i+32768));} return {b64:btoa(s),type:r.headers.get('content-type')||''}; }""",
                        src,
                    )
                    raw = base64.b64decode(encoded["b64"])
                    info = _image_info(raw, encoded.get("type", ""))
                    if info and len(raw) > 8192:
                        return raw, info[0]
                response = self.page.context.request.get(src, timeout=45000)
                if response.ok:
                    raw = response.body()
                    info = _image_info(raw, response.headers.get("content-type", ""))
                    if info and len(raw) > 8192:
                        return raw, info[0]
            except Exception:
                continue
        return None

    def generate_image(self, prompt: str, out_base: Path, *, timeout_ms: int = 360000) -> Path:
        self.open()
        self.new_chat()
        messages = self._assistant_messages()
        baseline_count = messages.count()
        try:
            baseline_sources = set(messages.locator("img").evaluate_all("imgs => imgs.map(i => i.currentSrc || i.src).filter(Boolean)"))
        except Exception:
            baseline_sources = set()
        self.image_candidates = []
        self._generation_started = time.time()
        request = (
            "Generate the image now. Do not just describe it. Create one polished visual for a short-form video.\n\n"
            + prompt
            + "\n\nNo captions, no visible UI, no watermark, no logo, and avoid accidental readable text unless specifically required."
        )
        self._fill_and_send(request)
        message, response_text = self._wait_response(baseline_count, timeout_ms)

        deadline = time.time() + 45
        while time.time() < deadline:
            if self.image_candidates:
                best = self.image_candidates[0]
                if best["width"] >= 768 and best["height"] >= 768:
                    break
            time.sleep(0.5)
        self._generation_started = 0.0

        if self.image_candidates:
            best = self.image_candidates[0]
            target = out_base.with_suffix(best["ext"])
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes(best["body"])
            return target

        dom = self._dom_image_bytes(message, baseline_sources)
        if dom:
            raw, ext = dom
            target = out_base.with_suffix(ext)
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes(raw)
            return target

        compact = _clean(response_text)[:500]
        raise RuntimeError("ChatGPT did not return a generated image. " + compact)


class ElevenLabsBrowserClient:
    URL = "https://elevenlabs.io/app/speech-synthesis/text-to-speech"

    def __init__(self):
        self.session: ChromeSession | None = None
        self.page = None
        self.audio_candidates: list[dict] = []
        self._capture = False
        self._observer_installed = False

    def open(self):
        if self.session and self.page and not self.page.is_closed():
            return self
        self.session = ChromeSession("elevenlabs", background=True).start()
        self.page = self.session.page
        if not self.page.url.startswith("https://elevenlabs.io"):
            self.page.goto(self.URL, wait_until="domcontentloaded", timeout=45000)
        status, message = detect_auth("elevenlabs", self.page)
        if status != "verified":
            raise RuntimeError(message)
        self._install_audio_observer()
        return self

    def close(self):
        if self.session:
            self.session.close()
        self.session = self.page = None

    def _install_audio_observer(self):
        if self._observer_installed:
            return

        def on_response(response):
            try:
                if not self._capture or not (200 <= response.status < 300):
                    return
                content_type = response.headers.get("content-type", "")
                url = response.url
                likely = content_type.lower().startswith("audio/") or re.search(r"text-to-speech|speech|audio|history", url, re.I)
                if not likely:
                    return
                body = response.body()
                if not body or len(body) < 10000:
                    return
                ext = _audio_ext(body, content_type)
                if not ext:
                    return
                score = len(body) + (2_000_000 if re.search(r"text-to-speech|speech", url, re.I) else 0)
                self.audio_candidates.append({"body": body, "ext": ext, "score": score})
                self.audio_candidates.sort(key=lambda x: x["score"], reverse=True)
                del self.audio_candidates[8:]
            except Exception:
                pass

        self.page.on("response", on_response)
        self._observer_installed = True

    def _editor(self):
        selectors = [
            'textarea[placeholder*="text" i]',
            'textarea[placeholder*="speech" i]',
            "textarea",
            '[contenteditable="true"][role="textbox"]',
            '[contenteditable="true"].ProseMirror',
            '[contenteditable="true"]',
        ]
        return self.page.locator(",".join(f"{s}:visible" for s in selectors)).first

    def _generate_button(self):
        return self.page.locator(
            'button:visible:has-text("Generate speech"),button:visible:has-text("Generate"),button[aria-label*="generate" i]:visible'
        ).first

    def render(self, text: str, out_dir: Path, *, timeout_ms: int = 240000) -> Path:
        self.open()
        if "/speech-synthesis" not in self.page.url:
            self.page.goto(self.URL, wait_until="domcontentloaded", timeout=45000)
        editor = self._editor()
        editor.wait_for(state="visible", timeout=20000)
        editor.click()
        try:
            editor.fill(text)
        except Exception:
            editor.press("Control+A")
            editor.press_sequentially(text, delay=1)

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
            raise RuntimeError("ElevenLabs finished without a capturable audio file. Keep the Text to Speech page open in the saved profile and retry. " + str(exc)) from exc


def get_chatgpt_client() -> ChatGPTBrowserClient:
    client = getattr(_thread, "chatgpt", None)
    if client is None:
        client = ChatGPTBrowserClient()
        _thread.chatgpt = client
    return client.open()


def get_eleven_client() -> ElevenLabsBrowserClient:
    client = getattr(_thread, "elevenlabs", None)
    if client is None:
        client = ElevenLabsBrowserClient()
        _thread.elevenlabs = client
    return client.open()


def close_thread_clients() -> None:
    for name in ("chatgpt", "elevenlabs"):
        client = getattr(_thread, name, None)
        if client:
            try:
                client.close()
            except Exception:
                pass
            setattr(_thread, name, None)


def _role_for(index: int, count: int) -> str:
    if index == 0:
        return "Hook"
    if index == count - 1:
        return "Landing"
    ratio = index / max(1, count - 1)
    if ratio < 0.22:
        return "Establishing"
    if ratio < 0.45:
        return "Action"
    if ratio < 0.65:
        return "Escalation"
    if ratio < 0.82:
        return "Peak"
    return "Aftermath"


def _broll_query(topic: str, narration: str) -> str:
    stop = {"the", "and", "that", "this", "with", "from", "into", "were", "was", "have", "has", "what", "when", "where", "would", "could", "about", "because", "their", "there", "then"}
    picks: list[str] = []
    for word in _words(narration):
        key = word.lower()
        if len(key) < 3 or key in stop:
            continue
        if key not in {x.lower() for x in picks}:
            picks.append(word)
        if len(picks) >= 4:
            break
    subject = " ".join(_words(topic)[:4])
    return " ".join([subject, *picks]).strip()[:100]


def _split_exact(text: str, count: int) -> list[str]:
    clean = _clean(text)
    words = clean.split()
    result: list[str] = []
    start = 0
    for i in range(count):
        end = round(len(words) * (i + 1) / count)
        result.append(" ".join(words[start:end]).strip())
        start = end
    return result


def custom_script(project, scene_count: int) -> tuple[str, list[Scene]]:
    text = (getattr(project, "custom_script", "") or project.script or "").strip()
    if not text:
        raise RuntimeError("Custom Script is empty")
    chunks = _split_exact(text, scene_count)
    scenes: list[Scene] = []
    for i, narration in enumerate(chunks):
        role = _role_for(i, scene_count)
        prompt = (
            f"{project.style}. {role} shot illustrating this narration: {narration}. "
            "Cinematic documentary composition, concrete subject and environment, no readable text, no captions, no logo, no watermark."
        )
        scene = Scene(i + 1, narration, prompt, max(2.0, project.target_seconds / scene_count))
        scene.shot_role = role
        scene.source_query = "Planned B-roll: " + _broll_query(project.topic, narration)
        scenes.append(scene)
    project.title = project.topic.strip()[:100] or "Custom Reel"
    project.script_model_used = "Custom Script"
    project.script_quality_summary = "Custom narration preserved • browser writer bypassed"
    return text, scenes


def chatgpt_browser_generate(self, project, scene_count: int):
    mode = getattr(project, "script_mode", "ChatGPT Browser") or "ChatGPT Browser"
    if mode == "Custom Script":
        return custom_script(project, scene_count)
    count = max(3, int(scene_count))
    research = (getattr(project, "research_context", "") or "").strip()
    target_words = max(45, round(float(project.target_seconds) * 2.35))
    prompt = f"""Write the complete narration and visual plan for a high-retention short-form video.

TOPIC: {project.topic}
STYLE: {project.style}
TARGET RUNTIME: {project.target_seconds} seconds
TARGET SPOKEN WORDS: about {target_words}
SCENES: exactly {count}
{('RESEARCH CONTEXT: ' + research) if research else ''}

SCRIPT RULES
- Scene 1 opens on the strongest concrete fact, consequence, conflict, mystery, reversal, or surprising question. No greetings or generic creator hooks.
- By scene 2 the viewer understands the premise and why it matters.
- Every scene adds new information; never paraphrase the previous scene just to fill time.
- Build clear cause-and-effect and place the strongest reveal/payoff near the final third when the subject supports it.
- Natural spoken English: contractions, varied sentence length, specific nouns, plain verbs, minimal filler.
- End with a memorable landing line, not a recap or generic CTA.
- For factual topics, do not invent quotations, dates, statistics, names, or events. If uncertain, phrase cautiously.

EDITING RULES
- image_prompt describes one useful visual beat with no captions, typography, logos, or watermark.
- broll_query is 2-7 literal searchable words for real footage.
- shot_role must be one of Hook, Establishing, Action, Detail, Escalation, Peak, Aftermath, Landing.
- Adjacent scenes should visibly differ.

Return ONLY valid JSON in this exact shape, with exactly {count} scene objects:
{{"title":"...","scenes":[{{"narration":"...","image_prompt":"...","broll_query":"...","shot_role":"Hook"}}]}}"""
    data = get_chatgpt_client().ask_json(prompt, timeout_ms=240000)
    rows = data.get("scenes", [])
    if len(rows) != count:
        raise RuntimeError(f"ChatGPT returned {len(rows)} scenes; expected {count}.")
    allowed = {"Hook", "Establishing", "Action", "Detail", "Escalation", "Peak", "Aftermath", "Landing"}
    scenes: list[Scene] = []
    for i, row in enumerate(rows):
        narration = _clean(str(row.get("narration", "")))
        image_prompt = _clean(str(row.get("image_prompt", "")))
        if not narration or not image_prompt:
            raise RuntimeError("ChatGPT returned an incomplete scene.")
        scene = Scene(i + 1, narration, image_prompt, max(2.0, project.target_seconds / count))
        role = str(row.get("shot_role") or "").strip()
        scene.shot_role = role if role in allowed else _role_for(i, count)
        query = _clean(str(row.get("broll_query") or "")) or _broll_query(project.topic, narration)
        scene.source_query = "Planned B-roll: " + query[:120]
        scenes.append(scene)
    project.title = _clean(str(data.get("title") or project.topic))[:100]
    script = " ".join(scene.narration for scene in scenes).strip()
    project.script = script
    project.script_model_used = "ChatGPT Browser"
    project.script_quality_summary = f"ChatGPT browser writer • {len(_words(script))} words"
    return script, scenes


def _tagless_words(text: str) -> list[str]:
    value = re.sub(r"\[[^\]]+\]", " ", text or "")
    return [w.casefold() for w in re.findall(r"[A-Za-z0-9]+(?:['’][A-Za-z0-9]+)?", value)]


def build_elevenlabs_script(project, progress=None) -> list[str]:
    count = len(project.scenes)
    if not count:
        return []
    source = "\n".join(f"{i + 1}. [{scene.shot_role or _role_for(i, count)}] {scene.narration}" for i, scene in enumerate(project.scenes))
    prompt = f"""Prepare this narration for an expressive ElevenLabs Text to Speech performance.

Add sparse square-bracket performance tags such as [shocked], [gasps], [whispers], [sighs], [laughs], [excited], [serious], [pause], and [long pause].
Preserve every spoken word exactly. Tags may direct emotion or nonverbal reactions, but must not rewrite narration, names, numbers, sentence order, or facts. Use 0-2 tags per scene unless the moment genuinely needs more. Do not use parentheses.

Return ONLY valid JSON: {{"scenes":[{{"text":"..."}}]}} with exactly {count} scene objects.

NARRATION:\n{source}"""
    try:
        if progress:
            progress(18, "ChatGPT browser • adding ElevenLabs performance tags")
        data = get_chatgpt_client().ask_json(prompt, timeout_ms=180000)
        tagged = [_clean(str(row.get("text", ""))) for row in data.get("scenes", [])]
        if len(tagged) != count:
            raise RuntimeError("Incomplete tagged script")
        for scene, value in zip(project.scenes, tagged):
            if _tagless_words(value) != _tagless_words(scene.narration):
                raise RuntimeError("Tagged script changed narration words")
        return tagged
    except Exception:
        result = []
        for scene in project.scenes:
            role = (scene.shot_role or "").lower()
            tag = "[shocked] " if role == "Hook".lower() else "[serious] " if role in {"escalation", "peak"} else "[sighs] " if role == "landing" else ""
            result.append(tag + scene.narration)
        return result


def _ffmpeg(settings) -> str:
    path = find_executable(getattr(settings, "ffmpeg_exe", ""), "ffmpeg")
    if path:
        return path
    try:
        import imageio_ffmpeg
        return imageio_ffmpeg.get_ffmpeg_exe()
    except Exception as exc:
        raise RuntimeError("FFmpeg is required to convert ElevenLabs browser audio.") from exc


class ElevenLabsBrowserVoiceService:
    def __init__(self, settings, delivery: str):
        self.settings = settings
        self.delivery = delivery

    def generate(self, project, out_dir: Path, progress=None) -> Path:
        tagged = build_elevenlabs_script(project, progress=progress)
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
            progress(20, "ElevenLabs browser • generating narration with saved profile")
        source = get_eleven_client().render(text, out_dir, timeout_ms=300000)
        target = out_dir / "narration.wav"
        if source.suffix.lower() == ".wav":
            target.write_bytes(source.read_bytes())
        else:
            proc = subprocess.run(
                [_ffmpeg(self.settings), "-y", "-i", str(source), "-ac", "1", "-ar", "44100", "-c:a", "pcm_s16le", str(target)],
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
            )
            if proc.returncode != 0:
                raise RuntimeError("Could not convert ElevenLabs browser audio to WAV: " + proc.stderr.decode("utf-8", errors="replace")[-1200:])
        duration = v070_voice._wav_duration(target)
        v070_voice.apply_scene_timing(project, duration, self.delivery)
        project.actual_seconds = round(duration, 2)
        project.voice_engine_used = ELEVEN_BROWSER_ENGINE
        project.voice_delivery = self.delivery
        if progress:
            progress(29, f"ElevenLabs browser narration ready • {duration:.1f}s")
        return target


class ChatGPTImageService:
    def __init__(self, settings):
        self.settings = settings

    def validate_server(self) -> None:
        get_chatgpt_client().open()

    def generate(self, scene, out_dir: Path, fmt: str) -> Path:
        prompt = (
            f"Create one {fmt} visual. {scene.image_prompt} "
            "Keep the important subject inside the safe center of frame for short-form video editing."
        )
        target = get_chatgpt_client().generate_image(prompt, out_dir / f"scene_{scene.index:03d}_chatgpt")
        scene.source_type = "ChatGPT Browser Image"
        scene.source_query = prompt[:240]
        return target


def browser_runtime_rewrite(settings, project, actual_seconds: float, progress=None, pass_index: int = 1) -> bool:
    if getattr(project, "script_mode", "ChatGPT Browser") == "Custom Script":
        return False
    target = float(project.target_seconds)
    if target <= 0 or actual_seconds <= 0 or 0.95 <= target / actual_seconds <= 1.05:
        return False
    count = len(project.scenes)
    draft = "\n".join(f"{i + 1}. {scene.narration}" for i, scene in enumerate(project.scenes))
    direction = "expand" if actual_seconds < target else "tighten"
    prompt = f"""Adjust this approved narration so spoken runtime moves from {actual_seconds:.1f}s toward {target:.1f}s. {direction.upper()} naturally.
Keep exactly {count} scenes in the same order and preserve facts, names, numbers, uncertainty, and causal meaning. Do not invent facts. Return ONLY valid JSON: {{"scenes":[{{"narration":"..."}}]}} with exactly {count} scenes.

DRAFT:\n{draft}"""
    try:
        if progress:
            progress(31, f"ChatGPT browser runtime lock • pass {pass_index}")
        data = get_chatgpt_client().ask_json(prompt, timeout_ms=180000)
        values = [_clean(str(row.get("narration", ""))) for row in data.get("scenes", [])]
        if len(values) != count or not all(values):
            return False
        for scene, value in zip(project.scenes, values):
            scene.narration = value
        project.script = " ".join(values)
        project.runtime_rewrites += 1
        return True
    except Exception:
        return False
