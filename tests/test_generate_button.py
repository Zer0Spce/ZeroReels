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
        from zeroreels.v052_script_base import install as install_v052_script_base
        from zeroreels.v052_hotfix import install as install_v052_hotfix
        from zeroreels.v053_quality import install as install_v053_quality
        from zeroreels.v053_duration import install as install_v053_duration
        from zeroreels.v053_render import install as install_v053_render
        from zeroreels.v060_pipeline import install as install_v060_pipeline
        from zeroreels.v060_render import install as install_v060_render
        from zeroreels.v060_guardrails import install as install_v060_guardrails
        from zeroreels.v060_ui import install as install_v060_ui

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
        install_v060_ui()

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

        assert window.style_box.currentText() == "TikTok Story"
        assert window.transition_style_box.currentText() == "Story Rhythm"
        assert window.caption_style_box.currentText() == "TikTok Pop"
        assert window.soundtrack_box.currentText() == "Auto Ambience"
        assert window.quality_guard_check.isChecked()
        assert window.sfx_check.isChecked()
        assert window.continuity_box.findText("Hero Character Lock") >= 0

        window.generate.click()
        app.processEvents()

        assert window.worker is not None, "Generate button did not create a pipeline worker"
        initial_log = window.create_live_log.toPlainText()
        assert "Starting a new ZeroReels generation" in initial_log
        assert "Live stage tracking connected" in initial_log
        assert "Professional polish:" in initial_log

        deadline = time.time() + 40
        while time.time() < deadline and window.worker.isRunning():
            app.processEvents()
            time.sleep(0.02)

        assert not window.worker.isRunning(), "Mock generation thread did not finish in time"
        for _ in range(80):
            app.processEvents()
            if window.current_project and window.current_project.video_path:
                break
            time.sleep(0.02)

        log = window.create_live_log.toPlainText()
        assert window.current_project is not None, log
        assert window.current_project.video_path, log
        assert "Initializing professional local pipeline" in log, log
        assert "Writing retention-first narration" in log, log
        assert "Generating scene 1/3" in log, log
        assert "Building TikTok Pop captions" in log, log
        assert "Starting final edit" in log, log
        assert "Mixing soundtrack, ducking and subtle SFX" in log, log
        assert "Video ready" in log, log
        assert "Preparing local pipeline • elapsed" not in log, log
        assert window.current_project.captions_path.endswith("captions.ass")
        assert window.current_project.soundtrack_used
        window.close()
        '''
    )
    env = os.environ.copy()
    env["QT_QPA_PLATFORM"] = "offscreen"
    proc = subprocess.run(
        [sys.executable, "-c", script],
        text=True,
        capture_output=True,
        timeout=55,
        env=env,
    )
    assert proc.returncode == 0, proc.stdout + "\n" + proc.stderr
