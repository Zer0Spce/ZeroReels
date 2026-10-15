from __future__ import annotations

import subprocess

from zeroreels import win_subprocess


def test_hidden_kwargs_are_noop_off_windows(monkeypatch):
    monkeypatch.setattr(win_subprocess.os, "name", "posix")
    original = {"cwd": "demo"}
    assert win_subprocess._windows_hidden_kwargs(original) == original


def test_hidden_kwargs_add_create_no_window_on_windows(monkeypatch):
    monkeypatch.setattr(win_subprocess.os, "name", "nt")
    result = win_subprocess._windows_hidden_kwargs({"creationflags": 4})
    expected = int(getattr(win_subprocess.subprocess, "CREATE_NO_WINDOW", 0x08000000))
    assert result["creationflags"] & expected
    assert result["creationflags"] & 4


def test_install_never_replaces_python_popen(monkeypatch):
    monkeypatch.setattr(win_subprocess.os, "name", "nt")
    original = subprocess.Popen
    win_subprocess.install()
    assert subprocess.Popen is original


def test_kokoro_import_still_works_after_no_console_helpers(monkeypatch):
    monkeypatch.setattr(win_subprocess.os, "name", "nt")
    win_subprocess.install()
    import kokoro_onnx  # noqa: F401
    import soundfile  # noqa: F401
