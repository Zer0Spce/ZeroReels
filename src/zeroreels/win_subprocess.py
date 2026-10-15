from __future__ import annotations

import os
import subprocess
from typing import Any


def _windows_hidden_kwargs(kwargs: dict[str, Any]) -> dict[str, Any]:
    """Return subprocess kwargs that hide only the child process ZeroReels launches."""
    if os.name != "nt":
        return dict(kwargs)
    updated = dict(kwargs)
    create_no_window = getattr(subprocess, "CREATE_NO_WINDOW", 0x08000000)
    updated["creationflags"] = int(updated.get("creationflags", 0) or 0) | int(create_no_window)
    if updated.get("startupinfo") is None and hasattr(subprocess, "STARTUPINFO"):
        startupinfo = subprocess.STARTUPINFO()
        startupinfo.dwFlags |= getattr(subprocess, "STARTF_USESHOWWINDOW", 0x00000001)
        startupinfo.wShowWindow = getattr(subprocess, "SW_HIDE", 0)
        updated["startupinfo"] = startupinfo
    return updated


def run_hidden(*args, **kwargs):
    """Run one ZeroReels-owned helper without flashing a Windows console."""
    return subprocess.run(*args, **_windows_hidden_kwargs(kwargs))


def popen_hidden(*args, **kwargs):
    """Launch one ZeroReels-owned helper without flashing a Windows console."""
    return subprocess.Popen(*args, **_windows_hidden_kwargs(kwargs))


def install() -> None:
    """Backward-compatible no-op.

    v0.7.2 replaced subprocess.Popen globally, which could interfere with Kokoro/phonemizer and
    other third-party packages. v0.7.3 intentionally leaves Python's subprocess module untouched.
    Call run_hidden/popen_hidden only for ZeroReels-owned external processes instead.
    """
    return None
