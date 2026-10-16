from __future__ import annotations

from PySide6.QtWidgets import QLabel

from . import ui, v116_integrity_chat, v117_elevenlabs_editor, v118_elevenlabs_paste, v119_elevenlabs_document


def _ordered_match_count(expected_words: list[str], actual_words: list[str]) -> int:
    matched = 0
    for token in actual_words:
        if matched < len(expected_words) and token == expected_words[matched]:
            matched += 1
    return matched


def _sequence_complete(expected: str, actual: str) -> bool:
    expected_words = v116_integrity_chat._spoken_signature(expected)
    actual_words = v116_integrity_chat._spoken_signature(actual)
    if not expected_words:
        return False
    return _ordered_match_count(expected_words, actual_words) == len(expected_words)


def _body_text(client) -> str:
    try:
        return str(client.page.locator("body").inner_text(timeout=3500) or "")
    except Exception:
        return ""


def _clipboard_text(client) -> str:
    try:
        return str(
            client.page.evaluate(
                """async () => {
                  if (!navigator.clipboard || !navigator.clipboard.readText) return '';
                  return await navigator.clipboard.readText();
                }"""
            )
            or ""
        )
    except Exception:
        return ""


def _copy_selection_views(client, editor) -> list[str]:
    values: list[str] = []
    try:
        try:
            client.page.context.grant_permissions(
                ["clipboard-read", "clipboard-write"], origin="https://elevenlabs.io"
            )
        except Exception:
            pass
        editor.click()
        client.page.keyboard.press("Control+A")
        client.page.keyboard.press("Control+C")
        client.page.wait_for_timeout(180)
        copied = _clipboard_text(client)
        if copied.strip():
            values.append(copied)
    except Exception:
        pass

    try:
        raw = editor.evaluate(
            """
            async el => {
              const out = [];
              let node = el;
              for (let depth = 0; node && depth < 10; depth += 1, node = node.parentElement) {
                try {
                  const selection = window.getSelection();
                  if (!selection) continue;
                  selection.removeAllRanges();
                  const range = document.createRange();
                  range.selectNodeContents(node);
                  selection.addRange(range);
                  document.execCommand('copy');
                  await new Promise(resolve => setTimeout(resolve, 30));
                  if (navigator.clipboard && navigator.clipboard.readText) {
                    const value = await navigator.clipboard.readText();
                    if (value && value.trim()) out.push(value);
                  }
                } catch (_) {}
              }
              try { window.getSelection()?.removeAllRanges(); } catch (_) {}
              return [...new Set(out)];
            }
            """
        )
        if isinstance(raw, list):
            values.extend(str(item or "") for item in raw if str(item or "").strip())
    except Exception:
        pass

    seen: set[str] = set()
    result: list[str] = []
    for value in values:
        key = value.strip()
        if key and key not in seen:
            seen.add(key)
            result.append(value)
    return result


def _verification_views(client, editor) -> list[str]:
    values: list[str] = []
    try:
        values.extend(v119_elevenlabs_document._document_texts(editor))
    except Exception:
        pass
    values.extend(_copy_selection_views(client, editor))
    body = _body_text(client)
    if body.strip():
        values.append(body)
    return values


def _best_evidence(client, editor, expected: str) -> tuple[str, int, bool]:
    expected_words = v116_integrity_chat._spoken_signature(expected)
    best_text = ""
    best_match = -1
    for text in _verification_views(client, editor):
        try:
            if v117_elevenlabs_editor._eleven_script_complete_v117(expected, text):
                return text, len(expected_words), True
        except Exception:
            pass
        actual_words = v116_integrity_chat._spoken_signature(text)
        matched = _ordered_match_count(expected_words, actual_words)
        if matched > best_match:
            best_match = matched
            best_text = text
        if matched == len(expected_words):
            return text, matched, True
    return best_text, max(0, best_match), False


def _verify(client, editor, expected: str) -> bool:
    return _best_evidence(client, editor, expected)[2]


def _insert_by_paragraph(client, editor, text: str) -> bool:
    if not v119_elevenlabs_document._clear_for_retry(client, editor):
        return False
    blocks = [part.strip() for part in text.split("\n\n") if part.strip()]
    if not blocks:
        return False
    try:
        editor.click()
        for index, block in enumerate(blocks):
            try:
                client.page.evaluate("value => navigator.clipboard.writeText(value)", block)
                client.page.keyboard.press("Control+V")
            except Exception:
                client.page.keyboard.insert_text(block)
            if index < len(blocks) - 1:
                client.page.keyboard.press("Enter")
            client.page.wait_for_timeout(80)
        client.page.wait_for_timeout(700)
        return _verify(client, editor, text)
    except Exception:
        return False


def _insert_candidate(client, editor, text: str) -> bool:
    if not v119_elevenlabs_document._clear_for_retry(client, editor):
        return False

    if v118_elevenlabs_paste._clipboard_paste(client, editor, text):
        client.page.wait_for_timeout(500)
        if _verify(client, editor, text):
            return True

    if _insert_by_paragraph(client, editor, text):
        return True

    try:
        tag = str(editor.evaluate("el => (el.tagName || '').toLowerCase()") or "")
    except Exception:
        tag = ""
    if tag in {"textarea", "input"}:
        try:
            if not v119_elevenlabs_document._clear_for_retry(client, editor):
                return False
            editor.fill(text)
            client.page.wait_for_timeout(600)
            return _verify(client, editor, text)
        except Exception:
            pass
    return False


def _insert_full_eleven_script_v1110(client, text: str):
    candidates = v118_elevenlabs_paste._candidate_editors(client)
    if not candidates:
        candidates = [v116_integrity_chat._best_eleven_editor(client)]

    expected_words = v116_integrity_chat._spoken_signature(text)
    best_text = ""
    best_match = -1

    for editor in candidates[:10]:
        try:
            editor.wait_for(state="visible", timeout=4000)
        except Exception:
            continue
        for _attempt in range(2):
            if _insert_candidate(client, editor, text):
                return editor
            evidence, matched, _complete = _best_evidence(client, editor, text)
            if matched > best_match:
                best_match = matched
                best_text = evidence

    exposed = len(v116_integrity_chat._spoken_signature(best_text))
    matched = max(0, best_match)
    missing = max(0, len(expected_words) - matched)
    raise RuntimeError(
        "ElevenLabs did not verify the complete narration through its editor, browser selection, or rendered page. "
        f"Expected {len(expected_words)} spoken words; best browser evidence exposed {exposed} and matched {matched} in order. "
        f"{missing} narration word token(s) are still missing. "
        "ZeroReels did not click Generate or spend a TTS generation."
    )


def install() -> None:
    v116_integrity_chat._insert_full_eleven_script = _insert_full_eleven_script_v1110

    previous_sidebar = ui.MainWindow._sidebar

    def sidebar_v1110(self):
        frame = previous_sidebar(self)
        for label in frame.findChildren(QLabel):
            if label.text().startswith("v0."):
                label.setText("v0.11.10 BROWSER")
                label.setMaximumWidth(160)
                break
        return frame

    ui.MainWindow._sidebar = sidebar_v1110
