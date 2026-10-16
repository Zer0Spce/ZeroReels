from __future__ import annotations

import re

from PySide6.QtWidgets import QLabel

from . import ui, v116_integrity_chat, v117_elevenlabs_editor, v118_elevenlabs_paste


def _document_texts(editor) -> list[str]:
    """Return increasingly broad text views around the chosen ElevenLabs editor.

    ElevenLabs can split one pasted script into sibling editable paragraph blocks. Reading
    only the originally selected child then looks like "scene 1 only" even when the full
    document is present. This inspects the editor and nearby structured ancestors and
    concatenates top-level editable descendants in DOM order.
    """
    try:
        raw = editor.evaluate(
            """
            el => {
              const textOf = node => {
                if (!node) return '';
                if (typeof node.value === 'string') return node.value || '';
                return node.innerText || node.textContent || '';
              };
              const out = [];
              let node = el;
              for (let depth = 0; node && depth < 9; depth += 1, node = node.parentElement) {
                const all = [];
                if (node.matches && (node.matches('[contenteditable="true"]') || node.matches('textarea,input,[role="textbox"]'))) {
                  all.push(node);
                }
                if (node.querySelectorAll) {
                  for (const child of node.querySelectorAll('[contenteditable="true"],textarea,input,[role="textbox"]')) {
                    all.push(child);
                  }
                }
                const unique = [...new Set(all)];
                const tops = unique.filter(item => !unique.some(other => other !== item && other.contains(item)));
                const combined = tops.map(textOf).filter(Boolean).join('\n\n');
                if (combined.trim()) out.push(combined);
                const own = textOf(node);
                if (own.trim()) out.push(own);
              }
              return [...new Set(out)];
            }
            """
        )
    except Exception:
        raw = []
    if not isinstance(raw, list):
        raw = []
    values = [str(value or "") for value in raw if str(value or "").strip()]
    direct = v116_integrity_chat._editor_text(editor)
    if direct.strip() and direct not in values:
        values.insert(0, direct)
    return values


def _ordered_match_count(expected_words: list[str], actual_words: list[str]) -> int:
    matched = 0
    for token in actual_words:
        if matched < len(expected_words) and token == expected_words[matched]:
            matched += 1
    return matched


def _best_document_view(expected: str, editor) -> tuple[str, int, bool]:
    expected_words = v116_integrity_chat._spoken_signature(expected)
    best_text = ""
    best_match = -1
    for text in _document_texts(editor):
        actual_words = v116_integrity_chat._spoken_signature(text)
        match = _ordered_match_count(expected_words, actual_words)
        if v117_elevenlabs_editor._eleven_script_complete_v117(expected, text):
            return text, len(expected_words), True
        if match > best_match:
            best_match = match
            best_text = text
    return best_text, max(0, best_match), False


def _document_complete(expected: str, editor) -> bool:
    return _best_document_view(expected, editor)[2]


def _clear_for_retry(client, editor) -> bool:
    # First use the v0.11.7 rich-editor clear logic.
    if v117_elevenlabs_editor._clear_editor(client, editor):
        client.page.wait_for_timeout(250)
        # If the selected node was only one paragraph, a normal Ctrl+A inside the editor
        # is the most reliable way to clear the whole rich document before rebuilding it.
        try:
            editor.click()
            client.page.keyboard.press("Control+A")
            client.page.keyboard.press("Backspace")
            client.page.wait_for_timeout(300)
        except Exception:
            pass
        return True
    return False


def _insert_by_paragraph(client, editor, text: str) -> bool:
    """Fallback that never sends embedded newlines through insertText.

    Each block is inserted separately and Enter creates the rich-editor paragraph boundary.
    This avoids browsers/editors that truncate a multi-line insert after the first block.
    """
    if not _clear_for_retry(client, editor):
        return False
    blocks = [part.strip() for part in re.split(r"\n\s*\n+", text or "") if part.strip()]
    if not blocks:
        return False
    try:
        editor.click()
        for index, block in enumerate(blocks):
            client.page.keyboard.insert_text(block)
            if index < len(blocks) - 1:
                client.page.keyboard.press("Enter")
        client.page.wait_for_timeout(1000)
        return _document_complete(text, editor)
    except Exception:
        return False


def _insert_candidate_v119(client, editor, text: str) -> bool:
    if not _clear_for_retry(client, editor):
        return False

    # Primary path: real clipboard paste from v0.11.8, but verify the entire structured
    # TTS document rather than just the one child locator that received focus.
    if v118_elevenlabs_paste._clipboard_paste(client, editor, text):
        client.page.wait_for_timeout(350)
        if _document_complete(text, editor):
            return True

    # If the site exposed only the first paragraph, rebuild the document one block at a
    # time with real Enter boundaries.
    if _insert_by_paragraph(client, editor, text):
        return True

    # Keep the textarea path for simpler ElevenLabs layouts.
    try:
        tag = str(editor.evaluate("el => (el.tagName || '').toLowerCase()") or "")
    except Exception:
        tag = ""
    if tag in {"textarea", "input"}:
        try:
            editor.fill(text)
            client.page.wait_for_timeout(600)
            return _document_complete(text, editor)
        except Exception:
            pass
    return False


def _insert_full_eleven_script_v119(client, text: str):
    candidates = v118_elevenlabs_paste._candidate_editors(client)
    if not candidates:
        candidates = [v116_integrity_chat._best_eleven_editor(client)]

    expected_words = v116_integrity_chat._spoken_signature(text)
    best_text = ""
    best_match = -1

    for editor in candidates[:8]:
        try:
            editor.wait_for(state="visible", timeout=4000)
        except Exception:
            continue
        for _attempt in range(2):
            if _insert_candidate_v119(client, editor, text):
                return editor
            view, matched, _complete = _best_document_view(text, editor)
            if matched > best_match:
                best_match = matched
                best_text = view

    exposed = len(v116_integrity_chat._spoken_signature(best_text))
    matched = max(0, best_match)
    missing = max(0, len(expected_words) - matched)
    raise RuntimeError(
        "ElevenLabs did not expose the complete narration across its structured TTS document. "
        f"Expected {len(expected_words)} spoken words; best document view exposed {exposed} and matched {matched} in order. "
        f"{missing} narration word token(s) are still missing. "
        "ZeroReels did not click Generate or spend a TTS generation."
    )


def install() -> None:
    v116_integrity_chat._insert_full_eleven_script = _insert_full_eleven_script_v119

    previous_sidebar = ui.MainWindow._sidebar

    def sidebar_v119(self):
        frame = previous_sidebar(self)
        for label in frame.findChildren(QLabel):
            if label.text().startswith("v0."):
                label.setText("v0.11.9 BROWSER")
                label.setMaximumWidth(152)
                break
        return frame

    ui.MainWindow._sidebar = sidebar_v119
