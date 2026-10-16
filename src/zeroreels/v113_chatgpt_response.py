from __future__ import annotations

import time

from PySide6.QtWidgets import QLabel

from . import browser_ai, browser_sessions, ui


TURN_QUERY = '[data-message-author-role],[data-testid^="conversation-turn-"],main article'
STOP_QUERY = 'button[data-testid="stop-button"]:visible,button[aria-label*="stop" i]:visible'
SEND_QUERY = 'button[data-testid="send-button"]:visible,button[data-testid*="send" i]:visible,button[aria-label*="send" i]:visible'


def _norm(text: str) -> str:
    return " ".join((text or "").split()).strip()


def _looks_like_prompt(text: str, prompt: str) -> bool:
    text_n = _norm(text)
    prompt_n = _norm(prompt)
    if not text_n or not prompt_n:
        return False
    if text_n == prompt_n:
        return True
    probe = prompt_n[:220]
    if len(probe) >= 80 and probe in text_n:
        return True
    if len(text_n) >= 80 and text_n[:220] in prompt_n:
        return True
    return False


def _snapshot_turns(page) -> list[dict]:
    script = r'''
    () => {
      const raw = Array.from(document.querySelectorAll('[data-message-author-role],[data-testid^="conversation-turn-"],main article'));
      const seen = new Set();
      const result = [];
      const clean = (value) => String(value || '').replace(/\s+/g, ' ').trim();

      for (let index = 0; index < raw.length; index += 1) {
        const node = raw[index];
        const turn = node.closest('[data-testid^="conversation-turn-"]') || node.closest('article') || node;
        if (seen.has(turn)) continue;
        seen.add(turn);

        const roleNode = turn.matches('[data-message-author-role]')
          ? turn
          : turn.querySelector('[data-message-author-role]');
        let role = roleNode?.getAttribute('data-message-author-role') || '';
        const labelText = clean([
          turn.getAttribute('aria-label') || '',
          turn.querySelector('h1,h2,h3,h4,h5,h6')?.innerText || '',
          turn.querySelector('[aria-label]')?.getAttribute('aria-label') || ''
        ].join(' ')).toLowerCase();
        if (!role && /chatgpt said|assistant|response/.test(labelText)) role = 'assistant';
        if (!role && /you said|user message|your message/.test(labelText)) role = 'user';

        const content = roleNode
          || turn.querySelector('.markdown,[class*="markdown"],[class*="prose"],[data-testid*="message-content"]')
          || turn;
        const text = clean(content.innerText || turn.innerText || '');
        if (!text) continue;

        const messageId = turn.getAttribute('data-message-id')
          || roleNode?.getAttribute('data-message-id')
          || '';
        const testId = turn.getAttribute('data-testid') || '';
        const articleIndex = turn.tagName?.toLowerCase() === 'article'
          ? Array.from(document.querySelectorAll('main article')).indexOf(turn)
          : -1;
        const key = messageId || testId || `${role || 'turn'}:${articleIndex}:${text.slice(0, 80)}`;
        result.push({ key, role, text, messageId, testId, articleIndex });
      }
      return result;
    }
    '''
    try:
        return list(page.evaluate(script) or [])
    except Exception:
        return []


def _baseline_snapshot(page) -> dict:
    turns = _snapshot_turns(page)
    return {
        "turns": turns,
        "keys": {str(turn.get("key", "")) for turn in turns},
        "texts": {_norm(str(turn.get("text", ""))) for turn in turns},
    }


def _is_new_turn(turn: dict, baseline: dict) -> bool:
    key = str(turn.get("key", ""))
    text = _norm(str(turn.get("text", "")))
    return (key and key not in baseline.get("keys", set())) or (text and text not in baseline.get("texts", set()))


def _select_reply_candidate(turns: list[dict], baseline: dict, prompt: str) -> dict | None:
    new_turns = [turn for turn in turns if _is_new_turn(turn, baseline)]

    # Explicit assistant role wins immediately.
    for turn in reversed(new_turns):
        if str(turn.get("role", "")).lower() == "assistant" and not _looks_like_prompt(str(turn.get("text", "")), prompt):
            return turn

    # Generic conversation-turn/article fallback. This covers ChatGPT UI variants where
    # data-message-author-role is omitted from the rendered turn container.
    for turn in reversed(new_turns):
        role = str(turn.get("role", "")).lower()
        text = _norm(str(turn.get("text", "")))
        if role == "user" or _looks_like_prompt(text, prompt):
            continue
        if len(text) >= 12:
            return turn
    return None


def _locate_turn(page, turn: dict):
    message_id = str(turn.get("messageId", "") or "")
    test_id = str(turn.get("testId", "") or "")
    role = str(turn.get("role", "") or "")
    article_index = int(turn.get("articleIndex", -1) or -1)
    if message_id:
        return page.locator(f'[data-message-id="{message_id}"]').last
    if test_id:
        return page.locator(f'[data-testid="{test_id}"]').last
    if role == "assistant":
        return page.locator('[data-message-author-role="assistant"]').last
    if article_index >= 0:
        return page.locator('main article').nth(article_index)
    return page.locator('main article,[data-testid^="conversation-turn-"]').last


def _composer_value(composer) -> str:
    try:
        return _norm(composer.input_value(timeout=700))
    except Exception:
        try:
            return _norm(composer.inner_text(timeout=700))
        except Exception:
            return ""


def _human_gate(page) -> None:
    if browser_sessions.detect_human_gate(page):
        raise RuntimeError(
            "ChatGPT requires human verification. Open Settings → Browser Accounts → ChatGPT → Open, complete it manually, then retry."
        )


def _fill_and_send_v113(self, prompt: str):
    composer = self._composer()
    composer.wait_for(state="visible", timeout=15000)
    composer.click()
    try:
        composer.fill(prompt)
    except Exception:
        try:
            composer.press("Control+A")
        except Exception:
            pass
        composer.press_sequentially(prompt, delay=1)

    filled = _composer_value(composer)
    if len(filled) < min(20, max(1, len(_norm(prompt)) // 6)):
        raise RuntimeError("ChatGPT editor did not accept the ZeroReels prompt.")

    send = self.page.locator(SEND_QUERY).first
    sent_with_button = False
    try:
        send.wait_for(state="visible", timeout=12000)
        send.click(timeout=12000)
        sent_with_button = True
    except Exception:
        composer.press("Enter")

    # Confirm dispatch instead of blindly entering the response wait. Current ChatGPT
    # normally clears/disables the composer or creates the user turn almost immediately.
    deadline = time.time() + 18
    while time.time() < deadline:
        _human_gate(self.page)
        current = _composer_value(composer)
        turns = _snapshot_turns(self.page)
        if not current or len(current) < max(12, len(_norm(prompt)) // 5):
            return {"method": "button" if sent_with_button else "enter", "turns": turns}
        if any(str(turn.get("role", "")).lower() == "user" and _looks_like_prompt(str(turn.get("text", "")), prompt) for turn in turns):
            return {"method": "button" if sent_with_button else "enter", "turns": turns}
        if (self.page.url or "").startswith("https://chatgpt.com/c/"):
            return {"method": "button" if sent_with_button else "enter", "turns": turns}
        time.sleep(0.3)

    raise RuntimeError(
        "ZeroReels filled ChatGPT, but the prompt never appeared to send. Open the ChatGPT profile and check for a popup, disabled Send button, or usage-limit message."
    )


def _wait_response_v113(self, baseline, timeout_ms: int = 180000, prompt: str = ""):
    # Accept the old integer baseline for compatibility with any callers not yet patched.
    if isinstance(baseline, int):
        snap = _baseline_snapshot(self.page)
        snap["legacy_count"] = baseline
        baseline = snap

    overall_deadline = time.time() + max(30, timeout_ms / 1000)
    no_reply_deadline = min(overall_deadline, time.time() + 90)
    selected = None
    selected_locator = None
    last_text = ""
    stable_since = time.time()
    last_activity = time.time()

    while time.time() < overall_deadline:
        _human_gate(self.page)
        turns = _snapshot_turns(self.page)
        candidate = _select_reply_candidate(turns, baseline, prompt)
        if candidate is not None:
            if selected is None or candidate.get("key") != selected.get("key"):
                selected = candidate
                selected_locator = _locate_turn(self.page, candidate)
                last_text = ""
                stable_since = time.time()
                last_activity = time.time()

            text = _norm(str(candidate.get("text", "")))
            if text and text != last_text:
                last_text = text
                stable_since = time.time()
                last_activity = time.time()
            else:
                stop_visible = False
                try:
                    stop_visible = self.page.locator(STOP_QUERY).count() > 0
                except Exception:
                    pass
                if last_text and not stop_visible and time.time() - stable_since >= 1.8:
                    return selected_locator, last_text

            # Once a response has visibly started, allow the configured overall timeout.
            no_reply_deadline = overall_deadline
        else:
            # A stop button or a fresh /c/ thread means ChatGPT is doing something; extend
            # the no-reply deadline modestly but never past the overall caller timeout.
            active = False
            try:
                active = self.page.locator(STOP_QUERY).count() > 0
            except Exception:
                pass
            if active:
                last_activity = time.time()
                no_reply_deadline = min(overall_deadline, time.time() + 45)

        if time.time() >= no_reply_deadline:
            latest = _snapshot_turns(self.page)
            tail = " | ".join(_norm(str(t.get("text", "")))[:160] for t in latest[-3:])
            raise RuntimeError(
                "ChatGPT accepted the prompt, but ZeroReels could not detect a new assistant turn within 90 seconds. "
                f"Current page: {self.page.url}. Recent visible turns: {tail or 'none detected'}."
            )
        time.sleep(0.35)

    if last_text:
        return selected_locator, last_text
    raise RuntimeError("ChatGPT response did not finish before the browser timeout.")


def _ask_text_v113(self, prompt: str, *, new_chat: bool = True, timeout_ms: int = 180000) -> str:
    self.open()
    if new_chat:
        self.new_chat()
    baseline = _baseline_snapshot(self.page)
    _fill_and_send_v113(self, prompt)
    _, text = _wait_response_v113(self, baseline, timeout_ms, prompt)
    return text


def _generate_image_v113(self, prompt, out_base, *, timeout_ms: int = 360000):
    # Reuse the existing image-generation path, but temporarily give it the modern
    # response helpers so the same conversation-turn fix applies to image requests too.
    return _ORIGINAL_GENERATE_IMAGE(self, prompt, out_base, timeout_ms=timeout_ms)


_ORIGINAL_GENERATE_IMAGE = browser_ai.ChatGPTBrowserClient.generate_image


def install() -> None:
    browser_ai.ChatGPTBrowserClient._fill_and_send = _fill_and_send_v113
    browser_ai.ChatGPTBrowserClient._wait_response = _wait_response_v113
    browser_ai.ChatGPTBrowserClient.ask_text = _ask_text_v113

    # Keep the image path compatible: it still calls _fill_and_send/_wait_response, which
    # are patched above. No separate duplicate implementation is needed.

    previous_sidebar = ui.MainWindow._sidebar

    def sidebar_v113(self):
        frame = previous_sidebar(self)
        for label in frame.findChildren(QLabel):
            if label.text().startswith("v0."):
                label.setText("v0.11.3 BROWSER")
                label.setMaximumWidth(152)
                break
        return frame

    ui.MainWindow._sidebar = sidebar_v113
