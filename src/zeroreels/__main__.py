from __future__ import annotations

import sys

from PySide6.QtWidgets import QApplication

from . import ui
from .ui import MainWindow
from .live_setup import install as install_live_setup
from .model_browse import install as install_model_browse
from .quality_services import install as install_quality_services
from .quality_ui import install as install_quality_ui


def main() -> int:
    install_live_setup()
    install_model_browse()
    install_quality_services()
    install_quality_ui()

    app = QApplication(sys.argv)
    app.setApplicationName("ZeroReels")
    app.setOrganizationName("ZeroReels")
    app.setStyle("Fusion")
    app.setStyleSheet(ui.build_stylesheet())
    window = MainWindow()
    if "--smoke-test" in sys.argv:
        # Used by Windows CI to prove the packaged executable can import and build the real UI.
        window.close()
        return 0
    window.show()
    return app.exec()


if __name__ == "__main__":
    raise SystemExit(main())
