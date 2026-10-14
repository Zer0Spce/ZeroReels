from __future__ import annotations

import sys

from PySide6.QtWidgets import QApplication

from .ui import MainWindow, build_stylesheet


def main() -> int:
    app = QApplication(sys.argv)
    app.setApplicationName("ZeroReels")
    app.setOrganizationName("ZeroReels")
    app.setStyle("Fusion")
    app.setStyleSheet(build_stylesheet())
    window = MainWindow()
    window.show()
    return app.exec()


if __name__ == "__main__":
    raise SystemExit(main())
