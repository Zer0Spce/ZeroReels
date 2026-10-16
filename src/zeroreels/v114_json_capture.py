from __future__ import annotations

import json
import re
import time
from pathlib import Path

from PySide6.QtWidgets import QLabel

from . import browser_ai, browser_sessions, ui


STOP_QUERY = 'button[data-testid="stop-button"]:visible,button[aria-label*="stop" i]:visible'


def _norm(value: str) -> str:
    return " ".join((value or "").split()).strip()


def _body_text(page, limit: int = 240_000) -> str:
    try:
        value = page.evaluate("() => document.body ? (document.body.innerText || document.body.textContent || '') : ''") or ""
    except Exception:
        return ""
    value = str(value)
    return value[-limit:] if len(value) > limit else value


def _extract_json_dicts(text: str, max_candidates: int = 700) -> list[dict]:
    """Find complete JSON objects embedded anywhere in visible page text.

    ChatGPT often renders JSON inside a code block while the surrounding page contains
    navigation text, prompts, buttons, and other UI. JSONDecoder.raw_decode lets us parse
    the object without depending on any ChatGPT-specific message wrapper.
    """
    source = text or ""
    decoder = json.JSONDecoder()
    found: list[dict] = []
    seen: set[str] = set()
    checked = 0
    for match in re.finditer(r"\{", source):
        if checked >= max_candidates:
            break
        checked += 1
        try:
            value, _ = decoder.raw_decode(source[match.start():])
        except Exception:
            continue
        if not isinstance(value, dict):
            continue
        try:
            fingerprint = json.dumps(value, sort_keys=True, ensure_ascii=False, separators=(",", ":"))
        except Exception:
            continue
        if fingerprint in seen:
            continue
        seen.add(fingerprint)
        found.append(value)
    return found


def _fingerprint(value: dict) -> str:
    return json.dumps(value, sort_keys=True, ensure_ascii=False, separators=(",", ":"))


def _json_fingerprints(text: str) -> set[str]:
    return {_fingerprint(value) for value in _extract_json_dicts(text)}


def _expected_scene_count(prompt: str) -> int | None:
    patterns = (
        r"exactly\s+(\d+)\s+scene(?:s|\s+objects?)?",
        r"with\s+exactly\s+(\d+)\s+scene",
        r"scenes\s*:\s*exactly\s+(\d+)",
    )
    for pattern in patterns:
        match = re.search(pattern, prompt or "", flags=re.IGNORECASE)
        if match:
            try:
                return max(1, int(match.group(1)))
            except Exception:
                pass
    return None


def _matches_prompt_schema(value: dict, prompt: str) -> bool:
    # Every browser-written ZeroReels payload today is scene-oriented. Keep a generic
    # fallback so the browser helper remains useful for a future JSON task too.
    prompt_lower = (prompt or "").lower()
    expects_scenes = '"scenes"' in prompt_lower or "scene objects" in prompt_lower
    if expects_scenes:
        scenes = value.get("scenes")
        if not isinstance(scenes, list):
            return False
        expected = _expected_scene_count(prompt)
        if expected is not None and len(scenes) != expected:
            return False
    return True


def _select_new_json(body_text: str, baseline_fps: set[str], prompt: str) -> dict | None:
    # The user prompt itself contains an example JSON schema. Explicitly ignore any JSON
    # copied from that prompt so ZeroReels cannot mistake the user's schema for ChatGPT's answer.
    ignored = set(baseline_fps)
    ignored.update(_json_fingerprints(prompt))
    candidates = _extract_json_dicts(body_text)
    for value in reversed(candidates):
        fp = _fingerprint(value)
        if fp in ignored:
            continue
        if _matches_prompt_schema(value, prompt):
            return value
    return None


def _assistant_texts_from_conversation(data: dict) -> list[str]:
    rows: list[tuple[float, str]] = []
    seen: set[str] = set()

    def inspect_message(message: dict) -> None:
        if not isinstance(message, dict):
            return
        author = message.get("author") or {}
        if not isinstance(author, dict) or str(author.get("role", "")).lower() != "assistant":
            return
        content = message.get("content") or {}
        if not isinstance(content, dict):
            return
        parts = content.get("parts") or []
        if not isinstance(parts, list):
            return
        chunks: list[str] = []
        for part in parts:
            if isinstance(part, str):
                chunks.append(part)
            elif isinstance(part, dict):
                # Some current response payloads put textual content in a nested text field.
                for key in ("text", "content", "value"):
                    nested = part.get(key)
                    if isinstance(nested, str):
                        chunks.append(nested)
                        break
        text = "\n".join(chunk for chunk in chunks if chunk).strip()
        if not text or text in seen:
            return
        seen.add(text)
        try:
            created = float(message.get("create_time") or 0)
        except Exception:
            created = 0.0
        rows.append((created, text))

    mapping = data.get("mapping") if isinstance(data, dict) else None
    if isinstance(mapping, dict):
        for node in mapping.values():
            if isinstance(node, dict):
                inspect_message(node.get("message") or {})

    # Future/alternate shapes: recursively inspect explicit message dictionaries.
    def walk(value) -> None:
        if isinstance(value, dict):
            if "author" in value and "content" in value:
                inspect_message(value)
            for child in value.values():
                walk(child)
        elif isinstance(value, list):
            for child in value:
                walk(child)

    if not rows:
        walk(data)
    rows.sort(key=lambda item: item[0])
    return [text for _, text in rows]


def _browser_conversation_texts(page) -> list[str]:
    """Read the current conversation through the already logged-in browser session.

    This is a fallback only. It runs inside chatgpt.com with the user's saved Chrome session,
    requires no API key, and avoids depending on transient CSS/message wrappers.
    """
    script = r'''
    async () => {
      const match = location.pathname.match(/^\/c\/([^/?#]+)/i);
      if (!match) return null;
      const id = match[1];
      const paths = [`/backend-api/conversation/${id}`, `/api/conversation/${id}`];
      for (const path of paths) {
        try {
          const response = await fetch(path, {
            method: 'GET',
            credentials: 'include',
            headers: { 'accept': 'application/json' }
          });
          if (!response.ok) continue;
          const data = await response.json();
          return data;
        } catch {}
      }
      return null;
    }
    '''
    try:
        data = page.evaluate(script)
    except Exception:
        return []
    if not isinstance(data, dict):
        return []
    return _assistant_texts_from_conversation(data)


def _stop_visible(page) -> bool:
    try:
        return page.locator(STOP_QUERY).count() > 0
    except Exception:
        return False


def _human_gate(page) -> None:
    if browser_sessions.detect_human_gate(page):
        raise RuntimeError(
            "ChatGPT requires human verification. Open Settings → Browser Accounts → ChatGPT → Open, complete it manually, then retry."
        )


def _wait_json_v114(self, baseline_fps: set[str], prompt: str, timeout_ms: int) -> dict:
    started = time.time()
    overall_deadline = started + max(30.0, timeout_ms / 1000.0)
    # Text JSON should appear quickly. Do not strand the whole render for four minutes again.
    no_json_deadline = min(overall_deadline, started + 120.0)
    next_conversation_probe = started + 4.0
    last_body = ""

    while time.time() < overall_deadline:
        _human_gate(self.page)
        body = _body_text(self.page)
        last_body = body or last_body
        value = _select_new_json(body, baseline_fps, prompt)
        if value is not None:
            return value

        now = time.time()
        # A completed/near-completed response may be available in ChatGPT's conversation
        # state even when the UI wrappers are opaque to Playwright.
        if now >= next_conversation_probe and (not _stop_visible(self.page) or now - started >= 12.0):
            for text in reversed(_browser_conversation_texts(self.page)):
                value = _select_new_json(text, baseline_fps, prompt)
                if value is not None:
                    return value
            next_conversation_probe = now + 2.0

        if now >= no_json_deadline:
            tail = _norm(last_body)[-900:]
            raise RuntimeError(
                "ChatGPT accepted the prompt, but ZeroReels could not find the requested JSON in the rendered page or current browser conversation. "
                f"Current page: {self.page.url}. Visible page tail: {tail or 'no readable page text'}"
            )
        time.sleep(0.28)

    raise RuntimeError("ChatGPT JSON response did not finish before the browser timeout.")


def _ask_json_v114(self, prompt: str, *, timeout_ms: int = 180000) -> dict:
    self.open()
    self.new_chat()
    baseline_fps = _json_fingerprints(_body_text(self.page))
    # _fill_and_send is the hardened v0.11.3 dispatch checker installed immediately before us.
    self._fill_and_send(prompt)
    return _wait_json_v114(self, baseline_fps, prompt, timeout_ms)


def _save_image_candidate(out_base: Path, candidate: dict) -> Path:
    target = out_base.with_suffix(candidate["ext"])
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_bytes(candidate["body"])
    return target


def _generate_image_v114(self, prompt: str, out_base: Path, *, timeout_ms: int = 360000) -> Path:
    self.open()
    self.new_chat()
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
            _human_gate(self.page)
            now = time.time()
            if self.image_candidates:
                best = self.image_candidates[0]
                if candidate_since is None:
                    candidate_since = now
                # Prefer the final asset after ChatGPT stops streaming. If the current UI
                # exposes no Stop control, a short stability delay still avoids grabbing a transient.
                if not _stop_visible(self.page) or now - candidate_since >= 4.0:
                    return _save_image_candidate(out_base, best)

            if now >= next_dom_probe:
                # Whole-page fallback: unlike v0.11.3 this does not require an assistant
                # message locator. It only accepts an image source that did not exist pre-send.
                dom = self._dom_image_bytes(self.page.locator("body"), baseline_sources)
                if dom:
                    raw, ext = dom
                    target = out_base.with_suffix(ext)
                    target.parent.mkdir(parents=True, exist_ok=True)
                    target.write_bytes(raw)
                    return target
                last_body = _body_text(self.page, limit=40_000)
                next_dom_probe = now + 3.0

            time.sleep(0.4)
    finally:
        self._generation_started = 0.0

    tail = _norm(last_body or _body_text(self.page, limit=40_000))[-700:]
    raise RuntimeError(
        "ChatGPT did not expose a generated image before the browser timeout. "
        f"Current page: {self.page.url}. Visible page tail: {tail or 'no readable page text'}"
    )


def install() -> None:
    # Text work in ZeroReels is JSON-contract based (script scenes, ElevenLabs performance
    # scenes, and runtime rewrites). Capture the contract itself instead of ChatGPT DOM wrappers.
    browser_ai.ChatGPTBrowserClient.ask_json = _ask_json_v114
    # Image generation now waits for image bytes directly and never depends on text bubbles.
    browser_ai.ChatGPTBrowserClient.generate_image = _generate_image_v114

    previous_sidebar = ui.MainWindow._sidebar

    def sidebar_v114(self):
        frame = previous_sidebar(self)
        for label in frame.findChildren(QLabel):
            if label.text().startswith("v0."):
                label.setText("v0.11.4 BROWSER")
                label.setMaximumWidth(152)
                break
        return frame

    ui.MainWindow._sidebar = sidebar_v114
