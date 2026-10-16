from __future__ import annotations

from zeroreels import v116_integrity_chat as v116
from zeroreels import v117_elevenlabs_editor as v117
from zeroreels import v118_elevenlabs_paste as v118


class _FakeContext:
    def __init__(self):
        self.clipboard = ""
        self.permissions = []

    def grant_permissions(self, permissions, origin=None):
        self.permissions.append((tuple(permissions), origin))


class _FakeKeyboard:
    def __init__(self, page):
        self.page = page

    def press(self, key):
        if key == "Control+V":
            assert self.page.active_editor is not None
            self.page.active_editor.text = self.page.context.clipboard


class _FakePage:
    def __init__(self):
        self.context = _FakeContext()
        self.keyboard = _FakeKeyboard(self)
        self.active_editor = None

    def evaluate(self, script, value=None):
        if "navigator.clipboard.writeText" in script:
            self.context.clipboard = value
            return None
        raise AssertionError("unexpected page.evaluate call")

    def wait_for_timeout(self, _milliseconds):
        return None


class _FakeEditor:
    def __init__(self, page, text=""):
        self.page = page
        self.text = text

    def click(self):
        self.page.active_editor = self

    def evaluate(self, script, value=None):
        if "tagName" in script:
            return "div"
        if "typeof el.value" in script:
            return self.text
        raise AssertionError("unexpected editor.evaluate call")


class _FakeClient:
    def __init__(self):
        self.page = _FakePage()


def test_clipboard_paste_keeps_complete_multiline_script(monkeypatch):
    client = _FakeClient()
    editor = _FakeEditor(client.page, "old stale narration")
    script = (
        "[serious] Scene one has several spoken words.\n\n"
        "[pause]\n\n"
        "Scene two must also survive the paste.\n\n"
        "[whispers] Scene three is the final paragraph."
    )

    def clear_editor(_client, target):
        target.text = ""
        return True

    monkeypatch.setattr(v117, "_clear_editor", clear_editor)

    assert v118._insert_candidate(client, editor, script)
    assert editor.text == script
    assert v117._eleven_script_complete_v117(script, editor.text)
    assert "Scene two" in editor.text
    assert "Scene three" in editor.text


def test_clipboard_helper_writes_full_text_before_ctrl_v():
    client = _FakeClient()
    editor = _FakeEditor(client.page)
    script = "first paragraph\n\nsecond paragraph\n\nthird paragraph"

    assert v118._clipboard_paste(client, editor, script)
    assert client.page.context.clipboard == script
    assert editor.text == script
    assert client.page.context.permissions


def test_full_multiline_signature_is_not_first_paragraph_only():
    full = "[serious] one two three.\n\n[pause]\n\nfour five six.\n\nseven eight nine."
    first = "[serious] one two three."
    assert len(v116._spoken_signature(full)) == 9
    assert len(v116._spoken_signature(first)) == 3
    assert not v117._eleven_script_complete_v117(full, first)
