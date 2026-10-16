from __future__ import annotations

import time

from PySide6.QtWidgets import QLabel

from . import browser_ai, browser_sessions, ui, v111_browser


_ORIGINAL_DETECT_AUTH = browser_sessions.detect_auth

CHATGPT_COMPOSERS = (
    "#prompt-textarea",
    '[data-testid="composer-text-input"]',
    '[data-testid="composer-textarea"]',
    '[data-testid*="composer"][contenteditable="true"]',
    'textarea[placeholder*="message" i]',
    'textarea[placeholder*="ask" i]',
    "textarea",
    '[contenteditable="true"][role="textbox"]',
    '[contenteditable="true"][data-placeholder]',
    '[data-lexical-editor="true"]',
    'div.ProseMirror[contenteditable="true"]',
    '[contenteditable="true"]',
)

CHATGPT_ACCOUNT_MARKERS = (
    '[data-testid="accounts-profile-button"]',
    '[data-testid*="profile-button"]',
    '[data-testid*="user-menu"]',
    'button[aria-label*="profile" i]',
    'button[aria-label*="account" i]',
    'button[aria-label*="user" i]',
    'nav a[href^="/c/"]',
    'a[href^="/c/"]',
)

CHATGPT_LOGIN_MARKERS = (
    'a[href*="/auth/login"]',
    'a[href*="/auth/signup"]',
    'button:has-text("Log in")',
    'button:has-text("Sign in")',
    'button:has-text("Sign up")',
    'a:has-text("Log in")',
    'a:has-text("Sign in")',
    'a:has-text("Sign up")',
)


def _visible(page, selector: str, timeout: int = 250) -> bool:
    try:
        locator = page.locator(selector).first
        try:
            return bool(locator.is_visible(timeout=timeout))
        except TypeError:
            locator.wait_for(state="visible", timeout=timeout)
            return True
    except Exception:
        return False


def _any_visible(page, selectors, timeout: int = 250) -> bool:
    return any(_visible(page, selector, timeout) for selector in selectors)


def _page_wait(page, ms: int) -> None:
    try:
        page.wait_for_timeout(ms)
    except Exception:
        time.sleep(ms / 1000)


def _chatgpt_probe(page) -> tuple[str, str]:
    url = (getattr(page, "url", "") or "").lower()
    if browser_sessions.detect_human_gate(page):
        return (
            "human-verification",
            "ChatGPT is asking for human verification. Complete it manually in Login Chrome, then retry.",
        )
    if any(token in url for token in ("/auth", "/login", "/signin", "/sign-in", "accounts.google.com")):
        return "needs-login", "ChatGPT is on a sign-in page."
    if _any_visible(page, CHATGPT_COMPOSERS, 300):
        return "verified", "ChatGPT editor detected in the saved ZeroReels Chrome profile."
    if _any_visible(page, CHATGPT_ACCOUNT_MARKERS, 180):
        return "verified", "ChatGPT account UI detected in the saved ZeroReels Chrome profile."
    if _any_visible(page, CHATGPT_LOGIN_MARKERS, 180):
        return "needs-login", "ChatGPT login controls are visible."
    return "unknown", "ChatGPT is still loading its workspace."


def detect_auth_v112(service_id: str, page, timeout_ms: int = 12000) -> tuple[str, str]:
    if service_id != "chatgpt":
        return _ORIGINAL_DETECT_AUTH(service_id, page)

    deadline = time.time() + max(0, timeout_ms) / 1000
    last = ("unknown", "ChatGPT is still loading its workspace.")
    while True:
        last = _chatgpt_probe(page)
        if last[0] != "unknown":
            return last
        if time.time() >= deadline:
            return last
        _page_wait(page, 350)


def _composer(self):
    selectors = ",".join(f"{selector}:visible" for selector in CHATGPT_COMPOSERS)
    return self.page.locator(selectors).first


def _wait_for_composer(self, timeout_ms: int = 25000):
    composer = _composer(self)
    composer.wait_for(state="visible", timeout=timeout_ms)
    return composer


def _ensure_ready(self):
    page = self.page
    if not (page.url or "").startswith("https://chatgpt.com"):
        page.goto("https://chatgpt.com/", wait_until="domcontentloaded", timeout=45000)

    status, message = detect_auth_v112("chatgpt", page, 15000)
    if status in {"needs-login", "human-verification"}:
        raise RuntimeError(message)

    # Do not abort on an inconclusive account-marker check. ChatGPT often mounts the page
    # shell first and the actual message editor several seconds later. The editor is the
    # capability ZeroReels really needs, and it can legitimately exist for a free session.
    try:
        _wait_for_composer(self, 25000)
        return
    except Exception:
        pass

    # A clean navigation handles stale service-worker shells and half-hydrated restored tabs.
    page.goto("https://chatgpt.com/", wait_until="domcontentloaded", timeout=45000)
    status, message = detect_auth_v112("chatgpt", page, 12000)
    if status in {"needs-login", "human-verification"}:
        raise RuntimeError(message)
    try:
        _wait_for_composer(self, 25000)
        return
    except Exception as exc:
        raise RuntimeError(
            "ChatGPT opened, but its message editor never became ready. Open Settings → Browser Accounts → ChatGPT → Open, confirm the normal ChatGPT page works, dismiss any welcome/update dialog, then retry."
        ) from exc


def test_session_v112(service_id: str) -> dict:
    service = browser_sessions.SERVICES[service_id]
    try:
        with browser_sessions.ChromeSession(service_id, background=False) as session:
            page = session.page
            base = service.url.split("/app/")[0]
            if not (page.url or "").startswith(base):
                page.goto(service.url, wait_until="domcontentloaded", timeout=45000)
            elif service_id != "chatgpt":
                page.reload(wait_until="domcontentloaded", timeout=45000)

            if service_id == "chatgpt":
                # The old v0.11.1 path reloaded the tab, waited only ~900 ms, and then checked
                # two selectors. Keep the existing tab alive and allow the modern UI to hydrate.
                status, message = detect_auth_v112("chatgpt", page, 18000)
                if status == "unknown":
                    try:
                        locator = page.locator(",".join(f"{s}:visible" for s in CHATGPT_COMPOSERS)).first
                        locator.wait_for(state="visible", timeout=20000)
                        status = "verified"
                        message = "ChatGPT editor is ready in the saved ZeroReels Chrome profile."
                    except Exception:
                        status, message = _chatgpt_probe(page)
                        if status == "unknown":
                            message = (
                                "ChatGPT loaded, but the editor is still unavailable. Open this profile, dismiss any welcome/update dialog, and run Test Session again."
                            )
            else:
                status, message = _ORIGINAL_DETECT_AUTH(service_id, page)
    except Exception as exc:
        status, message = "error", str(exc)

    browser_sessions.update_state(
        service_id,
        status=status,
        message=message,
        last_verified=time.strftime("%Y-%m-%dT%H:%M:%S"),
    )
    return {"ok": status == "verified", "status": status, "message": message}


def install() -> None:
    # Keep every consumer on the same readiness logic. browser_ai imported detect_auth by
    # value, and v111_browser imported test_session by value, so patch both references.
    browser_sessions.detect_auth = detect_auth_v112
    browser_sessions.test_session = test_session_v112
    browser_ai.detect_auth = detect_auth_v112
    browser_ai.ChatGPTBrowserClient.COMPOSERS = list(CHATGPT_COMPOSERS)
    browser_ai.ChatGPTBrowserClient._composer = _composer
    browser_ai.ChatGPTBrowserClient._ensure_ready = _ensure_ready
    v111_browser.test_session = test_session_v112

    # Preserve every v0.11.1 sidebar/UI patch already installed and only update the badge.
    previous_sidebar = ui.MainWindow._sidebar

    def sidebar_v112(self):
        frame = previous_sidebar(self)
        for label in frame.findChildren(QLabel):
            if label.text().startswith("v0."):
                label.setText("v0.11.2 BROWSER")
                label.setMaximumWidth(152)
                break
        return frame

    ui.MainWindow._sidebar = sidebar_v112
