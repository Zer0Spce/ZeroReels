from __future__ import annotations

import inspect

from PySide6.QtWidgets import QLabel

from . import live_setup, ui


_INSTALLED = False


def _invoke_setup_action(action, progress, log):
    """Call a setup action using the callback shape it actually accepts.

    ZeroReels has setup actions from several generations:
    - action()
    - action(progress)
    - action(progress, log)

    The Live Setup runner originally assumed every action accepted two callbacks, which broke
    the later Chatterbox/F5/Tesseract buttons because those actions only accepted progress.
    Inspecting the callable up front keeps backward compatibility without swallowing a real
    TypeError raised *inside* an installer.
    """
    try:
        signature = inspect.signature(action)
    except (TypeError, ValueError):
        # Unknown/builtin callables use the current two-callback contract.
        return action(progress, log)

    params = list(signature.parameters.values())
    if any(param.kind == inspect.Parameter.VAR_POSITIONAL for param in params):
        return action(progress, log)

    positional = [
        param
        for param in params
        if param.kind in (inspect.Parameter.POSITIONAL_ONLY, inspect.Parameter.POSITIONAL_OR_KEYWORD)
    ]
    if len(positional) >= 2:
        return action(progress, log)
    if len(positional) == 1:
        return action(progress)
    return action()


def _compatible_run(self) -> None:
    self.log_changed.emit(f"Starting: {self.label}")
    try:
        _invoke_setup_action(self.action, self.progress_changed.emit, self.log_changed.emit)
        self.log_changed.emit(f"Finished: {self.label}")
        self.completed.emit(self.label)
    except Exception as exc:
        message = str(exc) or exc.__class__.__name__
        self.log_changed.emit(f"ERROR: {message}")
        self.failed.emit(message)


def install() -> None:
    global _INSTALLED
    if _INSTALLED:
        return

    # Permanent compatibility fix for every setup button, old and new.
    live_setup.LiveSetupThread.run = _compatible_run
    ui.SetupThread = live_setup.LiveSetupThread

    # Keep the visible build badge truthful after the v0.7.1/v0.7.2 UI wrappers run.
    original_sidebar = ui.MainWindow._sidebar

    def sidebar(self):
        frame = original_sidebar(self)
        for label in frame.findChildren(QLabel):
            if label.text().startswith("v0."):
                label.setText("v0.7.4 FIX")
                label.setMaximumWidth(116)
                break
        return frame

    ui.MainWindow._sidebar = sidebar
    _INSTALLED = True
