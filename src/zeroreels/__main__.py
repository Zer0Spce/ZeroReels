from __future__ import annotations

import sys

from PySide6.QtWidgets import QApplication

from . import ui
from .ui import MainWindow
from .live_setup import install as install_live_setup
from .model_browse import install as install_model_browse
from .quality_services import install as install_quality_services
from .renderer_fix import install as install_renderer_fix
from .quality_orchestration import install as install_quality_orchestration
from .quality_ui import install as install_quality_ui
from .layout_polish import install as install_layout_polish
from .v051_hotfix import install as install_v051_hotfix
from .v052_script_base import install as install_v052_script_base
from .v052_hotfix import install as install_v052_hotfix
from .v053_quality import install as install_v053_quality


def main() -> int:
    install_live_setup()
    install_model_browse()
    install_quality_services()
    install_renderer_fix()
    install_quality_orchestration()
    install_quality_ui()
    install_layout_polish()
    install_v051_hotfix()
    install_v052_script_base()
    install_v052_hotfix()
    # Keep v0.5.3 last: it owns the final narration style, live-stage transport,
    # defaults, and visual-storytelling behavior.
    install_v053_quality()

    app = QApplication(sys.argv)
    app.setApplicationName("ZeroReels")
    app.setOrganizationName("ZeroReels")
    app.setStyle("Fusion")
    app.setStyleSheet(ui.build_stylesheet())
    window = MainWindow()
    if "--smoke-test" in sys.argv:
        window.close()
        return 0
    window.show()
    return app.exec()


if __name__ == "__main__":
    raise SystemExit(main())
