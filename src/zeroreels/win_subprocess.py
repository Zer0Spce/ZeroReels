from __future__ import annotations

import os
import subprocess
from typing import Any


_ORIGINAL_POPEN = subprocess.Popen
_INSTALLED = False


def _windows_hidden_kwargs(kwargs: dict[str, Any]) -> dict[str, Any]:
    """Return Popen kwargs that keep helper/FFmpeg consoles invisible on Windows."""
    if os.name != "nt":
        return kwargs
    updated = dict(kwargs)
    create_no_window = getattr(subprocess, "CREATE_NO_WINDOW", 0x08000000)
    updated["creationflags"] = int(updated.get("creationflags", 0) or 0) | int(create_no_window)
    if updated.get("startupinfo") is None and hasattr(subprocess, "STARTUPINFO"):
        startupinfo = subprocess.STARTUPINFO()
        startupinfo.dwFlags |= getattr(subprocess, "STARTF_USESHOWWINDOW", 0x00000001)
        startupinfo.wShowWindow = getattr(subprocess, "SW_HIDE", 0)
        updated["startupinfo"] = startupinfo
    return updated


def install() -> None:
    """Patch subprocess.Popen once so all ZeroReels child processes stay background-only.

    subprocess.run/check_call/check_output all resolve subprocess.Popen at call time, so this
    also covers older renderer/helper modules without having to remember creation flags at every
    individual FFmpeg or Python invocation.
    """
    global _INSTALLED
    if _INSTALLED or os.name != "nt":
        return

    def hidden_popen(*args, **kwargs):
        return _ORIGINAL_POPEN(*args, **_windows_hidden_kwargs(kwargs))

    subprocess.Popen = hidden_popen  # type: ignore[assignment]
    setattr(subprocess, "_zeroreels_no_console", True)
    _INSTALLED = True
