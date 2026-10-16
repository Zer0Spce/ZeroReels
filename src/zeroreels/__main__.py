from __future__ import annotations

import sys

from PySide6.QtWidgets import QApplication

from . import ui
from .branding import app_icon
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
from .v053_duration import install as install_v053_duration
from .v053_render import install as install_v053_render
from .v060_pipeline import install as install_v060_pipeline
from .v060_render import install as install_v060_render
from .v060_guardrails import install as install_v060_guardrails
from .v060_prompt_safe import install as install_v060_prompt_safe
from .v060_ui import install as install_v060_ui
from .v060_labels import install as install_v060_labels
from .v070_pipeline import install as install_v070_pipeline
from .v070_render import install as install_v070_render
from .v070_guardrails import install as install_v070_guardrails
from .v070_ui import install as install_v070_ui
from .v070_setup_extra import install as install_v070_setup_extra
from .v071_pipeline import install as install_v071_pipeline
from .v071_render import install as install_v071_render
from .v071_ui import install as install_v071_ui
from .v074_setup_fix import install as install_v074_setup_fix
from .v075_voice_fix import install as install_v075_voice_fix
from .v080_render import install as install_v080_render
from .v081_web_fix import install as install_v081_web_fix
from .v082_natural_voice import install as install_v082_natural_voice
from .v083_drama3 import install as install_v083_drama3
from .v090_editor import install as install_v090_editor
from .v100_story_media import install as install_v100_story_media
from .v111_browser import install as install_v111_browser
from .v111_polish import install as install_v111_polish
from .v112_chatgpt_auth import install as install_v112_chatgpt_auth
from .v113_chatgpt_response import install as install_v113_chatgpt_response
from .v114_json_capture import install as install_v114_json_capture


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
    install_v053_quality()
    install_v053_duration()
    install_v053_render()
    install_v060_pipeline()
    install_v060_render()
    install_v060_guardrails()
    install_v060_prompt_safe()
    install_v060_ui()
    install_v060_labels()
    install_v070_pipeline()
    install_v070_render()
    install_v070_guardrails()
    install_v070_ui()
    install_v070_setup_extra()
    install_v071_pipeline()
    install_v071_render()
    install_v071_ui()
    install_v074_setup_fix()
    install_v075_voice_fix()
    # Browser-first workflow: normal ChatGPT and ElevenLabs sites through ZeroReels profiles.
    install_v080_render()
    install_v081_web_fix()
    install_v082_natural_voice()
    install_v083_drama3()
    install_v090_editor()
    install_v100_story_media()
    install_v111_browser()
    install_v111_polish()
    install_v112_chatgpt_auth()
    install_v113_chatgpt_response()
    install_v114_json_capture()

    app = QApplication(sys.argv)
    app.setApplicationName("ZeroReels")
    app.setOrganizationName("ZeroReels")
    app.setStyle("Fusion")
    app.setStyleSheet(ui.build_stylesheet())
    icon = app_icon()
    app.setWindowIcon(icon)
    window = MainWindow()
    window.setWindowIcon(icon)
    if "--smoke-test" in sys.argv:
        window.close()
        return 0
    window.show()
    return app.exec()


if __name__ == "__main__":
    raise SystemExit(main())
