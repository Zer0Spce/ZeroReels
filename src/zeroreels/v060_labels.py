from __future__ import annotations

from PySide6.QtWidgets import QLabel

from . import ui


def install() -> None:
    original_settings_page = ui.MainWindow._settings_page

    def settings_page(self):
        page = original_settings_page(self)
        for label in page.findChildren(QLabel):
            if label.text() == "Music folder (future)":
                label.setText("Local music folder")
                label.setToolTip("Optional folder containing your own MP3/WAV/M4A/AAC/FLAC/OGG background tracks.")
        return page

    ui.MainWindow._settings_page = settings_page
