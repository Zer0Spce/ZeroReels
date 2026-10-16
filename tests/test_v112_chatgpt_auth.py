from __future__ import annotations

from zeroreels import browser_sessions
from zeroreels import v112_chatgpt_auth as auth


class _Locator:
    def __init__(self, visible: bool):
        self.visible = visible

    @property
    def first(self):
        return self

    def is_visible(self, timeout=None):
        return self.visible

    def wait_for(self, state="visible", timeout=None):
        if not self.visible:
            raise RuntimeError("not visible")

    def count(self):
        return 1 if self.visible else 0


class _Page:
    def __init__(self, visible=(), url="https://chatgpt.com/"):
        self.url = url
        self.visible = set(visible)

    def locator(self, selector: str):
        # Combined composer selectors are used by _composer; treat them as visible when any
        # underlying selector has been marked visible by the test.
        parts = [part.removesuffix(":visible") for part in selector.split(",")]
        return _Locator(any(part in self.visible for part in parts))

    def title(self):
        return "ChatGPT"

    def wait_for_timeout(self, ms: int):
        return None


def test_modern_contenteditable_composer_is_verified(monkeypatch):
    monkeypatch.setattr(browser_sessions, "detect_human_gate", lambda page: False)
    page = _Page({'[contenteditable="true"][role="textbox"]'})
    status, message = auth._chatgpt_probe(page)
    assert status == "verified"
    assert "editor" in message.lower()


def test_lexical_composer_is_supported(monkeypatch):
    monkeypatch.setattr(browser_sessions, "detect_human_gate", lambda page: False)
    page = _Page({'[data-lexical-editor="true"]'})
    status, _ = auth._chatgpt_probe(page)
    assert status == "verified"


def test_login_controls_still_require_login(monkeypatch):
    monkeypatch.setattr(browser_sessions, "detect_human_gate", lambda page: False)
    page = _Page({'a[href*="/auth/login"]'})
    status, message = auth._chatgpt_probe(page)
    assert status == "needs-login"
    assert "login" in message.lower()


def test_inconclusive_page_is_not_mislabeled_logged_out(monkeypatch):
    monkeypatch.setattr(browser_sessions, "detect_human_gate", lambda page: False)
    page = _Page()
    status, _ = auth.detect_auth_v112("chatgpt", page, timeout_ms=0)
    assert status == "unknown"


def test_account_marker_can_verify_saved_profile(monkeypatch):
    monkeypatch.setattr(browser_sessions, "detect_human_gate", lambda page: False)
    page = _Page({'[data-testid="accounts-profile-button"]'})
    status, message = auth._chatgpt_probe(page)
    assert status == "verified"
    assert "account" in message.lower()


def test_composer_selector_set_covers_current_editor_shapes():
    assert "#prompt-textarea" in auth.CHATGPT_COMPOSERS
    assert '[contenteditable="true"][role="textbox"]' in auth.CHATGPT_COMPOSERS
    assert '[data-lexical-editor="true"]' in auth.CHATGPT_COMPOSERS
    assert 'div.ProseMirror[contenteditable="true"]' in auth.CHATGPT_COMPOSERS
