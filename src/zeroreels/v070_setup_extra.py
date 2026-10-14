from __future__ import annotations

from pathlib import Path
import os
import shutil
import subprocess

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QGridLayout, QLabel

from . import ui


def _progress(progress, value: int, text: str) -> None:
    if progress:
        progress(value, text)


def _find_tesseract() -> Path | None:
    direct = shutil.which("tesseract")
    if direct:
        return Path(direct)
    candidates = [
        Path("C:/Program Files/Tesseract-OCR/tesseract.exe"),
        Path(os.environ.get("LOCALAPPDATA", "")) / "Programs" / "Tesseract-OCR" / "tesseract.exe",
    ]
    for path in candidates:
        if path.exists():
            return path
    return None


def install_tesseract(settings, progress=None) -> None:
    existing = _find_tesseract()
    if existing:
        settings.ocr_exe = str(existing)
        settings.save()
        _progress(progress, 100, f"Tesseract OCR ready: {existing}")
        return
    winget = shutil.which("winget")
    if not winget:
        raise RuntimeError("Windows Package Manager (winget) is required for one-click OCR setup. You can also install Tesseract manually and select tesseract.exe in Settings.")
    _progress(progress, 5, "Installing Tesseract OCR for readable-text Visual QA")
    proc = subprocess.Popen(
        [
            winget, "install", "-e", "--id", "UB-Mannheim.TesseractOCR",
            "--accept-package-agreements", "--accept-source-agreements", "--silent",
        ],
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
        errors="replace",
    )
    lines = 0
    tail: list[str] = []
    assert proc.stdout is not None
    for raw in proc.stdout:
        line = raw.strip()
        if not line:
            continue
        lines += 1
        tail.append(line)
        tail = tail[-10:]
        _progress(progress, min(92, 8 + lines), line[-180:])
    code = proc.wait()
    if code != 0:
        raise RuntimeError("Tesseract installer failed:\n" + "\n".join(tail[-8:]))
    path = _find_tesseract()
    if not path:
        raise RuntimeError("Tesseract installation completed, but ZeroReels could not locate tesseract.exe. Select it manually in Settings.")
    settings.ocr_exe = str(path)
    settings.save()
    if hasattr(settings, "save"):
        settings.save()
    _progress(progress, 100, f"Tesseract OCR ready: {path}")


def install() -> None:
    original_setup_page = ui.MainWindow._setup_page
    original_settings_page = ui.MainWindow._settings_page

    def setup_page(self):
        page = original_setup_page(self)
        for label in page.findChildren(QLabel):
            if label.text() != "Finish":
                continue
            card = label.parentWidget()
            if not card or not card.layout():
                continue
            note = QLabel("Optional OCR catches readable AI-generated signs, documents and labels so Visual QA v2 can regenerate them.")
            note.setObjectName("Hint")
            note.setWordWrap(True)
            button = ui.SoftButton("Install Tesseract OCR (Optional)")
            button.clicked.connect(
                lambda: self._run_setup(
                    "Tesseract OCR ready",
                    lambda p: install_tesseract(self.settings, p),
                )
            )
            card.layout().addWidget(note)
            card.layout().addWidget(button)
            break
        return page

    def settings_page(self):
        page = original_settings_page(self)
        # v0.7 adds new fields after the legacy Save button. Move Save back to the bottom
        # so the advanced settings page reads cleanly from top to bottom.
        cards = page.findChildren(ui.Card)
        if not cards:
            return page
        grid = cards[0].layout()
        if not isinstance(grid, QGridLayout):
            return page
        save = None
        for button in cards[0].findChildren(ui.SoftButton):
            if button.text() == "Save Settings":
                save = button
                break
        if save:
            grid.removeWidget(save)
            grid.addWidget(save, grid.rowCount() + 1, 1, alignment=Qt.AlignRight)
        return page

    ui.MainWindow._setup_page = setup_page
    ui.MainWindow._settings_page = settings_page
