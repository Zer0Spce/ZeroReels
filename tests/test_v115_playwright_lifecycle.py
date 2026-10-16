from __future__ import annotations

from zeroreels import browser_ai, v115_playwright_lifecycle as lifecycle


class DummyClient:
    def __init__(self, name: str, events: list[str]):
        self.name = name
        self.events = events
        self.closed = False

    def close(self):
        self.closed = True
        self.events.append(f"close:{self.name}")


def _reset_thread_clients():
    for name in ("chatgpt", "elevenlabs"):
        setattr(browser_ai._thread, name, None)


def test_switching_chatgpt_to_elevenlabs_closes_chatgpt_first(monkeypatch):
    events: list[str] = []
    chat = DummyClient("chatgpt", events)
    eleven = DummyClient("elevenlabs", events)
    browser_ai._thread.chatgpt = chat
    browser_ai._thread.elevenlabs = None

    def original_eleven():
        assert chat.closed is True
        events.append("open:elevenlabs")
        browser_ai._thread.elevenlabs = eleven
        return eleven

    monkeypatch.setattr(lifecycle, "_ORIGINAL_GET_ELEVEN", original_eleven)
    result = lifecycle._get_eleven_client_v115()

    assert result is eleven
    assert browser_ai._thread.chatgpt is None
    assert events == ["close:chatgpt", "open:elevenlabs"]
    _reset_thread_clients()


def test_switching_elevenlabs_to_chatgpt_closes_elevenlabs_first(monkeypatch):
    events: list[str] = []
    chat = DummyClient("chatgpt", events)
    eleven = DummyClient("elevenlabs", events)
    browser_ai._thread.chatgpt = None
    browser_ai._thread.elevenlabs = eleven

    def original_chatgpt():
        assert eleven.closed is True
        events.append("open:chatgpt")
        browser_ai._thread.chatgpt = chat
        return chat

    monkeypatch.setattr(lifecycle, "_ORIGINAL_GET_CHATGPT", original_chatgpt)
    result = lifecycle._get_chatgpt_client_v115()

    assert result is chat
    assert browser_ai._thread.elevenlabs is None
    assert events == ["close:elevenlabs", "open:chatgpt"]
    _reset_thread_clients()


def test_same_service_is_not_closed_when_requested(monkeypatch):
    events: list[str] = []
    chat = DummyClient("chatgpt", events)
    browser_ai._thread.chatgpt = chat
    browser_ai._thread.elevenlabs = None

    monkeypatch.setattr(lifecycle, "_ORIGINAL_GET_CHATGPT", lambda: chat)
    result = lifecycle._get_chatgpt_client_v115()

    assert result is chat
    assert chat.closed is False
    assert events == []
    _reset_thread_clients()
