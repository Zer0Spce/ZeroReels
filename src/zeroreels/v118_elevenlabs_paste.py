from __future__ import annotations

from PySide6.QtWidgets import QLabel

from . import ui, v116_integrity_chat, v117_elevenlabs_editor


def _candidate_editors(client):
    """Return large visible TTS editor candidates, best first."""
    selectors = [
        '[contenteditable="true"].ProseMirror',
        '[role="textbox"][contenteditable="true"]',
        'textarea[placeholder*="text" i]',
        'textarea[placeholder*="speech" i]',
        'textarea',
        '[contenteditable="true"]',
    ]
    seen: set[str] = set()
    rows = []
    for priority, selector in enumerate(selectors):
        locator = client.page.locator(f"{selector}:visible")
        try:
            count = locator.count()
        except Exception:
            continue
        for index in range(min(count, 16)):
            item = locator.nth(index)
            try:
                data = item.evaluate(
                    """el => ({
                      key: (el.id || '') + '|' + (el.getAttribute('data-testid') || '') + '|' +
                           (el.getAttribute('aria-label') || '') + '|' + String(el.className || ''),
                      tag: (el.tagName || '').toLowerCase(),
                      role: el.getAttribute('role') || '',
                      placeholder: el.getAttribute('placeholder') || '',
                      cls: String(el.className || '')
                    })"""
                )
                box = item.bounding_box()
                if not box:
                    continue
                width = float(box.get("width", 0))
                height = float(box.get("height", 0))
                area = width * height
                if width < 280 or height < 80 or area < 28_000:
                    continue
                key = str(data.get("key") or f"{selector}:{index}")
                if key in seen:
                    continue
                seen.add(key)
                hint = " ".join(
                    str(data.get(name, "")) for name in ("placeholder", "role", "cls", "key")
                ).lower()
                score = area
                if "prosemirror" in hint:
                    score += 4_000_000
                if "textbox" in hint:
                    score += 2_000_000
                if "speech" in hint or "text" in hint:
                    score += 800_000
                if data.get("tag") == "textarea":
                    score += 500_000
                score -= priority * 20_000
                rows.append((score, item))
            except Exception:
                continue
    rows.sort(key=lambda row: row[0], reverse=True)
    return [item for _score, item in rows]


def _clipboard_paste(client, editor, text: str) -> bool:
    """Paste the full multiline script through Chrome's clipboard."""
    try:
        try:
            client.page.context.grant_permissions(
                ["clipboard-read", "clipboard-write"], origin="https://elevenlabs.io"
            )
        except Exception:
            pass
        client.page.evaluate(
            """async value => {
              if (!navigator.clipboard || !navigator.clipboard.writeText) {
                throw new Error('Clipboard API unavailable');
              }
              await navigator.clipboard.writeText(value);
            }""",
            text,
        )
        editor.click()
        client.page.keyboard.press("Control+V")
        client.page.wait_for_timeout(900)
        return True
    except Exception:
        return False


def _dispatch_paste_event(client, editor, text: str) -> bool:
    """Fallback when navigator.clipboard is blocked."""
    try:
        editor.evaluate(
            """
            (el, value) => {
              el.focus();
              const dt = new DataTransfer();
              dt.setData('text/plain', value);
              const event = new ClipboardEvent('paste', {
                clipboardData: dt,
                bubbles: true,
                cancelable: true
              });
              el.dispatchEvent(event);
            }
            """,
            text,
        )
        client.page.wait_for_timeout(900)
        return True
    except Exception:
        return False


def _insert_candidate(client, editor, text: str) -> bool:
    if not v117_elevenlabs_editor._clear_editor(client, editor):
        return False

    if _clipboard_paste(client, editor, text):
        actual = v116_integrity_chat._editor_text(editor)
        if v117_elevenlabs_editor._eleven_script_complete_v117(text, actual):
            return True

    if not v117_elevenlabs_editor._clear_editor(client, editor):
        return False
    if _dispatch_paste_event(client, editor, text):
        actual = v116_integrity_chat._editor_text(editor)
        if v117_elevenlabs_editor._eleven_script_complete_v117(text, actual):
            return True

    try:
        tag = str(editor.evaluate("el => (el.tagName || '').toLowerCase()") or "")
    except Exception:
        tag = ""
    if tag in {"textarea", "input"}:
        try:
            if not v117_elevenlabs_editor._clear_editor(client, editor):
                return False
            editor.fill(text)
            client.page.wait_for_timeout(700)
            return v117_elevenlabs_editor._eleven_script_complete_v117(
                text, v116_integrity_chat._editor_text(editor)
            )
        except Exception:
            pass
    return False


def _insert_full_eleven_script_v118(client, text: str):
    candidates = _candidate_editors(client)
    if not candidates:
        candidates = [v116_integrity_chat._best_eleven_editor(client)]

    best_actual = ""
    best_count = -1
    expected_words = v116_integrity_chat._spoken_signature(text)

    for editor in candidates[:8]:
        try:
            editor.wait_for(state="visible", timeout=4000)
        except Exception:
            continue
        for _attempt in range(2):
            if _insert_candidate(client, editor, text):
                return editor
            actual = v116_integrity_chat._editor_text(editor)
            count = len(v116_integrity_chat._spoken_signature(actual))
            if count > best_count:
                best_count = count
                best_actual = actual

    actual_words = v116_integrity_chat._spoken_signature(best_actual)
    missing = max(0, len(expected_words) - len(actual_words))
    raise RuntimeError(
        "ElevenLabs did not accept the complete multiline narration. "
        f"Expected {len(expected_words)} spoken words; the best editor candidate exposed {len(actual_words)}. "
        f"{missing} narration word token(s) are still missing. "
        "ZeroReels did not click Generate or spend a TTS generation."
    )


def install() -> None:
    v116_integrity_chat._insert_full_eleven_script = _insert_full_eleven_script_v118

    previous_sidebar = ui.MainWindow._sidebar

    def sidebar_v118(self):
        frame = previous_sidebar(self)
        for label in frame.findChildren(QLabel):
            if label.text().startswith("v0."):
                label.setText("v0.11.8 BROWSER")
                label.setMaximumWidth(152)
                break
        return frame

    ui.MainWindow._sidebar = sidebar_v118
