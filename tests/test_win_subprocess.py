from __future__ import annotations

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
