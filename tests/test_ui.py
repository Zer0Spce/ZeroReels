import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtWidgets import QApplication

from zeroreels.ui import MainWindow


def test_main_window_builds():
    app = QApplication.instance() or QApplication([])
    window = MainWindow()
    assert window.windowTitle().startswith("ZeroReels")
    assert window.pages.count() == 5
    assert window.mock.isChecked()
    window.close()
