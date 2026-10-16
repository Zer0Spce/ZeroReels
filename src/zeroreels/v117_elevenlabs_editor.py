from __future__ import annotations

import re

from PySide6.QtWidgets import QLabel

from . import browser_ai, ui, v116_integrity_chat


def _tag_words(expected: str) -> list[str]:
    words: list[str] = []
    for raw in re.findall(r"\[([^\]]+)\]", expected or ""):
        words.extend(browser_ai._tagless_words(raw))
    return words


def _eleven_script_complete_v117(expected: str, actual: str) -> bool:
    """Verify all spoken narration while tolerating ElevenLabs tag chips.

    ElevenLabs may render `[pause]` / `[serious]` as rich-text chips whose innerText is
    just `pause` / `serious`. Those labels are not spoken narration and must not make a
    complete paste look longer. Any other extra text (for example stale narration from a
    previous generation) still fails verification.
    """
    expected_words = v116_integrity_chat._spoken_signature(expected)
    actual_words = v116_integrity_chat._spoken_signature(actual)
    if not expected_words:
        return False
    if actual_words == expected_words:
        return True

    allowed_tag_words = _tag_words(expected)
    allowed = set(allowed_tag_words)
    matched = 0
    extras = 0
    for token in actual_words:
        if matched < len(expected_words) and token == expected_words[matched]:
            matched += 1
            continue
        if token in allowed:
            extras += 1
            continue
        return False

    if matched != len(expected_words):
        return False

    # Rich editors can expose one or two text nodes for a chip. Be generous enough for
    # that representation, but never accept arbitrary stale prose.
    return extras <= max(6, len(allowed_tag_words) * 2 + 2)


def _editor_empty(editor) -> bool:
    return len(v116_integrity_chat._spoken_signature(v116_integrity_chat._editor_text(editor))) == 0


def _select_all_contents(editor) -> None:
    editor.evaluate(
        """
        el => {
          el.focus();
          const selection = window.getSelection();
          if (!selection) return;
          selection.removeAllRanges();
          const range = document.createRange();
          range.selectNodeContents(el);
          selection.addRange(range);
        }
        """
    )


def _clear_editor(client, editor) -> bool:
    """Clear textarea or rich contenteditable and prove it is actually empty."""
    try:
        tag = str(editor.evaluate("el => (el.tagName || '').toLowerCase()") or "")
    except Exception:
        tag = ""

    if tag in {"textarea", "input"}:
        try:
            editor.fill("")
            client.page.wait_for_timeout(250)
            if _editor_empty(editor):
                return True
        except Exception:
            pass

    # ProseMirror/contenteditable: select the entire editor DOM range and delete it.
    for key in ("Backspace", "Delete"):
        try:
            editor.click()
            _select_all_contents(editor)
            client.page.keyboard.press(key)
            client.page.wait_for_timeout(250)
            if _editor_empty(editor):
                return True
        except Exception:
            pass

    # Strong fallback. Update the native value/content and emit the events React editors
    # listen for, then verify before any new narration is inserted.
    try:
        editor.evaluate(
            """
            el => {
              el.focus();
              if (typeof el.value === 'string') {
                const proto = el.tagName === 'TEXTAREA' ? HTMLTextAreaElement.prototype : HTMLInputElement.prototype;
                const descriptor = Object.getOwnPropertyDescriptor(proto, 'value');
                if (descriptor && descriptor.set) descriptor.set.call(el, '');
                else el.value = '';
              } else {
                while (el.firstChild) el.removeChild(el.firstChild);
                el.appendChild(document.createElement('br'));
              }
              try {
                el.dispatchEvent(new InputEvent('beforeinput', {bubbles:true, inputType:'deleteContentBackward'}));
              } catch {}
              try {
                el.dispatchEvent(new InputEvent('input', {bubbles:true, inputType:'deleteContentBackward'}));
              } catch {
                el.dispatchEvent(new Event('input', {bubbles:true}));
              }
              el.dispatchEvent(new Event('change', {bubbles:true}));
            }
            """
        )
        client.page.wait_for_timeout(350)
        return _editor_empty(editor)
    except Exception:
        return False


def _insert_once(client, editor, text: str) -> bool:
    try:
        tag = str(editor.evaluate("el => (el.tagName || '').toLowerCase()") or "")
    except Exception:
        tag = ""

    if tag in {"textarea", "input"}:
        try:
            editor.fill(text)
            client.page.wait_for_timeout(450)
            return _eleven_script_complete_v117(text, v116_integrity_chat._editor_text(editor))
        except Exception:
            return False

    # The reliable rich-editor path: clear first, select the whole empty editor, then one
    # insertText operation. This avoids per-character typing and replaces any stale blocks.
    try:
        editor.click()
        client.page.keyboard.insert_text(text)
        client.page.wait_for_timeout(450)
        if _eleven_script_complete_v117(text, v116_integrity_chat._editor_text(editor)):
            return True
    except Exception:
        pass

    # Last rich-text fallback: select all current editor contents and replace in one shot.
    try:
        _select_all_contents(editor)
        client.page.keyboard.insert_text(text)
        client.page.wait_for_timeout(450)
        return _eleven_script_complete_v117(text, v116_integrity_chat._editor_text(editor))
    except Exception:
        return False


def _insert_full_eleven_script_v117(client, text: str):
    editor = v116_integrity_chat._best_eleven_editor(client)
    editor.wait_for(state="visible", timeout=20000)

    # Two complete attempts are intentional: some ElevenLabs rich editors restore their
    # previous ProseMirror state after the first DOM/input event cycle.
    for _attempt in range(2):
        if not _clear_editor(client, editor):
            continue
        if _insert_once(client, editor, text):
            return editor

    expected_words = v116_integrity_chat._spoken_signature(text)
    actual_text = v116_integrity_chat._editor_text(editor)
    actual_words = v116_integrity_chat._spoken_signature(actual_text)
    difference = len(actual_words) - len(expected_words)
    detail = (
        f"The editor has {abs(difference)} extra word token(s), usually stale text from a previous generation."
        if difference > 0
        else f"The editor is missing {abs(difference)} word token(s)."
        if difference < 0
        else "The editor word count matches, but the narration sequence is different."
    )
    raise RuntimeError(
        "ElevenLabs editor could not be cleanly replaced with the complete narration. "
        f"Expected {len(expected_words)} spoken words; editor currently exposes {len(actual_words)}. "
        + detail
        + " ZeroReels did not click Generate or spend a TTS generation."
    )


def install() -> None:
    # v0.11.6's render/TTS guard remains in place; only upgrade the rich-editor verifier
    # and replacement routine it calls.
    v116_integrity_chat._eleven_script_complete = _eleven_script_complete_v117
    v116_integrity_chat._insert_full_eleven_script = _insert_full_eleven_script_v117

    previous_sidebar = ui.MainWindow._sidebar

    def sidebar_v117(self):
        frame = previous_sidebar(self)
        for label in frame.findChildren(QLabel):
            if label.text().startswith("v0."):
                label.setText("v0.11.7 BROWSER")
                label.setMaximumWidth(152)
                break
        return frame

    ui.MainWindow._sidebar = sidebar_v117
