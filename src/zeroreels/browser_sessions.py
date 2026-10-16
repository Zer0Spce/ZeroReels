from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
import json
import os
import shutil
import socket
import subprocess
import time
import urllib.request

from .config import APP_DIR


PROFILE_ROOT = APP_DIR / "browser_profiles"
STATE_FILE = APP_DIR / "browser_sessions.json"


@dataclass(frozen=True, slots=True)
class BrowserService:
    id: str
    name: str
    url: str
    auth_urls: tuple[str, ...]


SERVICES = {
    "chatgpt": BrowserService(
        "chatgpt",
        "ChatGPT",
        "https://chatgpt.com/",
        ("/auth", "/login", "/signin", "/sign-in", "accounts.google.com"),
    ),
    "elevenlabs": BrowserService(
        "elevenlabs",
        "ElevenLabs",
        "https://elevenlabs.io/app/speech-synthesis/text-to-speech",
        ("/sign-in", "/signin", "/login", "accounts.google.com"),
    ),
}


def _creation_flags(hidden: bool = True) -> int:
    if os.name != "nt":
        return 0
    return subprocess.CREATE_NO_WINDOW if hidden else 0


def find_chrome_executable() -> str | None:
    candidates = [
        os.environ.get("CHROME_PATH", ""),
        str(Path(os.environ.get("PROGRAMFILES", "")) / "Google" / "Chrome" / "Application" / "chrome.exe") if os.environ.get("PROGRAMFILES") else "",
        str(Path(os.environ.get("PROGRAMFILES(X86)", "")) / "Google" / "Chrome" / "Application" / "chrome.exe") if os.environ.get("PROGRAMFILES(X86)") else "",
        str(Path(os.environ.get("LOCALAPPDATA", "")) / "Google" / "Chrome" / "Application" / "chrome.exe") if os.environ.get("LOCALAPPDATA") else "",
    ]
    for value in candidates:
        if value and Path(value).exists():
            return str(Path(value))
    return shutil.which("chrome") or shutil.which("chrome.exe")


def require_chrome() -> str:
    value = find_chrome_executable()
    if not value:
        raise RuntimeError("Google Chrome was not found. ZeroReels browser automation uses Chrome with its own saved profiles.")
    return value


def profile_path(service_id: str) -> Path:
    if service_id not in SERVICES:
        raise ValueError(f"Unknown browser service: {service_id}")
    return PROFILE_ROOT / f"{service_id}-chrome"


def _load_state() -> dict:
    try:
        return json.loads(STATE_FILE.read_text(encoding="utf-8")) if STATE_FILE.exists() else {}
    except Exception:
        return {}


def _save_state(data: dict) -> None:
    APP_DIR.mkdir(parents=True, exist_ok=True)
    STATE_FILE.write_text(json.dumps(data, indent=2), encoding="utf-8")


def update_state(service_id: str, **patch) -> dict:
    data = _load_state()
    current = dict(data.get(service_id) or {})
    current.update(patch)
    data[service_id] = current
    _save_state(data)
    return current


def service_status(service_id: str) -> dict:
    service = SERVICES[service_id]
    state = _load_state().get(service_id) or {}
    path = profile_path(service_id)
    saved = path.exists() and any(path.iterdir())
    return {
        "id": service_id,
        "name": service.name,
        "saved": saved,
        "status": state.get("status", "unknown" if saved else "not-configured"),
        "message": state.get("message", "Saved Chrome profile found." if saved else "Login has not been configured yet."),
        "last_verified": state.get("last_verified"),
        "profile": str(path),
    }


def all_statuses() -> dict[str, dict]:
    return {service_id: service_status(service_id) for service_id in SERVICES}


def _free_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.bind(("127.0.0.1", 0))
        return int(sock.getsockname()[1])


def _wait_cdp(port: int, timeout: float = 20.0) -> None:
    deadline = time.time() + timeout
    last = ""
    while time.time() < deadline:
        try:
            with urllib.request.urlopen(f"http://127.0.0.1:{port}/json/version", timeout=1.5) as response:
                if response.status == 200:
                    return
        except Exception as exc:
            last = str(exc)
        time.sleep(0.2)
    raise RuntimeError(f"Chrome did not expose its local automation endpoint. {last}".strip())


def kill_profile_processes(service_id: str) -> None:
    if os.name != "nt":
        return
    path = str(profile_path(service_id)).replace("'", "''")
    script = (
        f"$p='{path}'; "
        "Get-CimInstance Win32_Process -Filter \"Name='chrome.exe'\" | "
        "Where-Object { $_.CommandLine -and $_.CommandLine.Contains($p) } | "
        "ForEach-Object { Stop-Process -Id $_.ProcessId -Force -ErrorAction SilentlyContinue }"
    )
    try:
        subprocess.run(
            ["powershell.exe", "-NoProfile", "-NonInteractive", "-ExecutionPolicy", "Bypass", "-Command", script],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            creationflags=_creation_flags(True),
            timeout=15,
            check=False,
        )
    except Exception:
        pass
    time.sleep(0.35)


def launch_login_browser(service_id: str) -> dict:
    service = SERVICES[service_id]
    chrome = require_chrome()
    kill_profile_processes(service_id)
    path = profile_path(service_id)
    path.mkdir(parents=True, exist_ok=True)
    process = subprocess.Popen(
        [chrome, f"--user-data-dir={path}", "--no-first-run", "--no-default-browser-check", service.url],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        creationflags=_creation_flags(False),
    )
    update_state(
        service_id,
        status="login-open",
        message=f"{service.name} login opened in ZeroReels' dedicated Chrome profile. Finish login/2FA/CAPTCHA there, then click Test Session.",
        last_login_opened=time.strftime("%Y-%m-%dT%H:%M:%S"),
    )
    return {"ok": True, "pid": process.pid, "profile": str(path)}


def open_service_browser(service_id: str) -> dict:
    return launch_login_browser(service_id)


def reset_profile(service_id: str) -> dict:
    kill_profile_processes(service_id)
    shutil.rmtree(profile_path(service_id), ignore_errors=True)
    data = _load_state()
    data.pop(service_id, None)
    _save_state(data)
    return {"ok": True}


class ChromeSession:
    """Attach Playwright to normal Google Chrome using a ZeroReels-owned profile.

    Login is always done in a normal Chrome process without a debugging flag. Automation
    starts later, with the same user-data directory and a localhost-only CDP port.
    """

    def __init__(self, service_id: str, *, background: bool = True):
        self.service_id = service_id
        self.service = SERVICES[service_id]
        self.background = background
        self.process: subprocess.Popen | None = None
        self.playwright = None
        self.browser = None
        self.context = None
        self.page = None
        self.port = 0

    def start(self):
        from playwright.sync_api import sync_playwright

        chrome = require_chrome()
        path = profile_path(self.service_id)
        if not path.exists():
            raise RuntimeError(f"{self.service.name} is not connected. Open Settings → Browser Accounts → Login Chrome first.")
        kill_profile_processes(self.service_id)
        time.sleep(0.35)
        path.mkdir(parents=True, exist_ok=True)
        try:
            (path / "DevToolsActivePort").unlink(missing_ok=True)
        except Exception:
            pass
        self.port = _free_port()
        args = [
            chrome,
            f"--user-data-dir={path}",
            f"--remote-debugging-port={self.port}",
            "--remote-debugging-address=127.0.0.1",
            "--no-first-run",
            "--no-default-browser-check",
            self.service.url,
        ]
        self.process = subprocess.Popen(
            args,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            creationflags=_creation_flags(False),
        )
        try:
            _wait_cdp(self.port)
            self.playwright = sync_playwright().start()
            self.browser = self.playwright.chromium.connect_over_cdp(f"http://127.0.0.1:{self.port}")
            contexts = self.browser.contexts
            self.context = contexts[0] if contexts else None
            if self.context is None:
                raise RuntimeError(f"{self.service.name} opened in Chrome, but ZeroReels could not attach to the saved profile.")
            pages = self.context.pages
            self.page = next((p for p in pages if p.url.startswith(self.service.url.split('/app/')[0])), pages[0] if pages else self.context.new_page())
            if not self.page.url.startswith(self.service.url.split('/app/')[0]):
                self.page.goto(self.service.url, wait_until="domcontentloaded", timeout=45000)
            if self.background:
                self._move_offscreen()
            return self
        except Exception:
            self.close()
            raise

    def _move_offscreen(self) -> None:
        try:
            session = self.context.new_cdp_session(self.page)
            result = session.send("Browser.getWindowForTarget")
            window_id = result.get("windowId")
            if window_id:
                session.send("Browser.setWindowBounds", {"windowId": window_id, "bounds": {"windowState": "normal"}})
                session.send(
                    "Browser.setWindowBounds",
                    {"windowId": window_id, "bounds": {"left": -20000, "top": -20000, "width": 1280, "height": 900}},
                )
            session.detach()
        except Exception:
            pass

    def close(self) -> None:
        try:
            if self.browser:
                self.browser.close()
        except Exception:
            pass
        try:
            if self.playwright:
                self.playwright.stop()
        except Exception:
            pass
        if self.process and self.process.poll() is None:
            try:
                self.process.terminate()
                self.process.wait(timeout=3)
            except Exception:
                try:
                    self.process.kill()
                except Exception:
                    pass
        self.browser = self.context = self.page = self.playwright = self.process = None
        kill_profile_processes(self.service_id)

    def __enter__(self):
        return self.start()

    def __exit__(self, exc_type, exc, tb):
        self.close()


def _visible(page, selector: str, timeout: int = 600) -> bool:
    try:
        locator = page.locator(selector).first
        locator.wait_for(state="visible", timeout=timeout)
        return True
    except Exception:
        return False


def detect_human_gate(page) -> bool:
    try:
        if _visible(page, "text=/verify you are human/i", 350):
            return True
        if page.locator('iframe[src*="challenges.cloudflare.com"]').count():
            return True
        title = page.title()
        return "just a moment" in title.lower() or "attention required" in title.lower()
    except Exception:
        return False


def detect_auth(service_id: str, page) -> tuple[str, str]:
    service = SERVICES[service_id]
    url = (page.url or "").lower()
    if service_id == "chatgpt" and detect_human_gate(page):
        return "human-verification", "ChatGPT is asking for human verification. Complete it manually in Login Chrome, then test again."
    if any(token in url for token in service.auth_urls):
        return "needs-login", f"{service.name} is on a sign-in page."

    if service_id == "chatgpt":
        if _visible(page, "#prompt-textarea", 1200) or _visible(page, '[data-testid="composer-text-input"]', 400):
            return "verified", "ChatGPT composer detected in the saved ZeroReels Chrome profile."
        if _visible(page, "text=/^(log in|sign in|sign up)$/i", 300):
            return "needs-login", "ChatGPT login controls are visible."
    else:
        if _visible(page, "text=/^(sign in|log in)$/i", 300):
            return "needs-login", "ElevenLabs login controls are visible."
        if "/app/" in url:
            return "verified", "ElevenLabs app is open in the saved ZeroReels Chrome profile."
    return "unknown", f"{service.name} opened, but ZeroReels could not confidently verify the login state."


def test_session(service_id: str) -> dict:
    service = SERVICES[service_id]
    try:
        with ChromeSession(service_id, background=False) as session:
            page = session.page
            if not page.url.startswith(service.url.split('/app/')[0]):
                page.goto(service.url, wait_until="domcontentloaded", timeout=45000)
            else:
                page.reload(wait_until="domcontentloaded", timeout=45000)
            page.wait_for_timeout(900)
            status, message = detect_auth(service_id, page)
    except Exception as exc:
        status, message = "error", str(exc)
    update_state(service_id, status=status, message=message, last_verified=time.strftime("%Y-%m-%dT%H:%M:%S"))
    return {"ok": status == "verified", "status": status, "message": message}
