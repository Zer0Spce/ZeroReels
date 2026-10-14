from __future__ import annotations

import os
import subprocess
import sys
import textwrap


def test_generate_button_starts_and_finishes_mock_pipeline():
    script = textwrap.dedent(
        r'''
        import os
        import time
        os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

        from PySide6.QtWidgets import QApplication
        from zeroreels import ui
        from zeroreels.ui import MainWindow
        from zeroreels.live_setup import install as install_live_setup
        from zeroreels.model_browse import install as install_model_browse
        from zeroreels.quality_services import install as install_quality_services
        from zeroreels.renderer_fix import install as install_renderer_fix
        from zeroreels.quality_orchestration import install as install_quality_orchestration
        from zeroreels.quality_ui import install as install_quality_ui
        from zeroreels.layout_polish import install as install_layout_polish
        from zeroreels.v051_hotfix import install as install_v051_hotfix

        install_live_setup()
        install_model_browse()
        install_quality_services()
        install_renderer_fix()
        install_quality_orchestration()
        install_quality_ui()
        install_layout_polish()
        install_v051_hotfix()

        app = QApplication([])
        app.setStyle("Fusion")
        app.setStyleSheet(ui.build_stylesheet())
        window = MainWindow()
        window.topic.setPlainText("A tiny lighthouse test")
        window.test_mode.setChecked(True)
        window.format_box.setCurrentText("1:1")
        window.seconds.setMinimum(6)
        window.seconds.setValue(6)
        window.scene_count.setValue(3)

        window.generate.click()
        app.processEvents()

        assert window.worker is not None, "Generate button did not create a pipeline worker"
        assert "Starting a new ZeroReels generation" in window.create_live_log.toPlainText()

        assert window.worker.wait(30000), "Mock generation thread did not finish in time"
        for _ in range(30):
            app.processEvents()
            if window.current_project and window.current_project.video_path:
                break
            time.sleep(0.02)

        log = window.create_live_log.toPlainText()
        assert window.current_project is not None, log
        assert window.current_project.video_path, log
        assert "Video ready" in log, log
        window.close()
        '''
    )
    env = os.environ.copy()
    env["QT_QPA_PLATFORM"] = "offscreen"
    proc = subprocess.run(
        [sys.executable, "-c", script],
        text=True,
        capture_output=True,
        timeout=45,
        env=env,
    )
    assert proc.returncode == 0, proc.stdout + "\n" + proc.stderr
