from __future__ import annotations

from PySide6.QtWidgets import QLabel

from . import browser_ai, ui


_ORIGINAL_GET_CHATGPT = browser_ai.get_chatgpt_client
_ORIGINAL_GET_ELEVEN = browser_ai.get_eleven_client


def _close_client(name: str) -> None:
    client = getattr(browser_ai._thread, name, None)
    if client is None:
        return
    try:
        client.close()
    except Exception:
        pass
    setattr(browser_ai._thread, name, None)


def _get_chatgpt_client_v115():
    # Playwright Sync API cannot safely start another sync_playwright() while a
    # different browser client's sync driver is already alive on this thread.
    # ZeroReels' pipeline is sequential, so release ElevenLabs before ChatGPT.
    _close_client("elevenlabs")
    return _ORIGINAL_GET_CHATGPT()


def _get_eleven_client_v115():
    # Script + performance-tag work finishes in ChatGPT before ElevenLabs TTS.
    # Fully stop ChatGPT's Playwright driver first so ElevenLabs can start a clean
    # sync driver without tripping Playwright's nested asyncio-loop guard.
    _close_client("chatgpt")
    return _ORIGINAL_GET_ELEVEN()


def install() -> None:
    browser_ai.get_chatgpt_client = _get_chatgpt_client_v115
    browser_ai.get_eleven_client = _get_eleven_client_v115

    previous_sidebar = ui.MainWindow._sidebar

    def sidebar_v115(self):
        frame = previous_sidebar(self)
        for label in frame.findChildren(QLabel):
            if label.text().startswith("v0."):
                label.setText("v0.11.5 BROWSER")
                label.setMaximumWidth(152)
                break
        return frame

    ui.MainWindow._sidebar = sidebar_v115
