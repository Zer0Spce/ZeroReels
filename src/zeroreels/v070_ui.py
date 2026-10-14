from __future__ import annotations

from pathlib import Path

from PySide6.QtWidgets import QCheckBox, QComboBox, QGridLayout, QLabel, QLineEdit

from . import ui
from .v070_voice import DELIVERY_PROFILES, install_optional_voice_engine


def _combo(items: list[str], current: str) -> QComboBox:
    box = QComboBox()
    box.addItems(items)
    box.setCurrentText(current)
    return box


def install() -> None:
    original_sidebar = ui.MainWindow._sidebar
    original_create_page = ui.MainWindow._create_page
    original_setup_page = ui.MainWindow._setup_page
    original_settings_page = ui.MainWindow._settings_page
    original_options = ui.MainWindow._options
    original_generate = ui.MainWindow._generate
    original_complete = ui.MainWindow._on_complete

    def sidebar(self):
        frame = original_sidebar(self)
        for label in frame.findChildren(QLabel):
            if label.text().startswith("v0."):
                label.setText("v0.7 HUMAN")
                label.setMaximumWidth(108)
                break
        return frame

    def create_page(self):
        page = original_create_page(self)
        quality_card = self.continuity_box.parentWidget()
        grid = quality_card.layout()
        if not isinstance(grid, QGridLayout):
            return page

        # Caption auto-safe and semantic sound design become the Human Touch defaults.
        positions = [self.caption_position_box.itemText(i) for i in range(self.caption_position_box.count())]
        if "Auto Safe" not in positions:
            self.caption_position_box.insertItem(0, "Auto Safe")
        self.caption_position_box.setCurrentText("Auto Safe")
        if hasattr(self, "soundtrack_box"):
            sounds = [self.soundtrack_box.itemText(i) for i in range(self.soundtrack_box.count())]
            if "Smart Soundscape" not in sounds:
                self.soundtrack_box.insertItem(0, "Smart Soundscape")
            self.soundtrack_box.setCurrentText("Smart Soundscape")

        self.voice_engine_box = _combo(
            ["Kokoro Directed", "Kokoro Classic", "Chatterbox Nano", "F5-TTS Studio"],
            getattr(self.settings, "voice_engine", "Kokoro Directed"),
        )
        self.voice_engine_box.setToolTip(
            "Kokoro Directed is built in and generates a more continuous performance. Chatterbox Nano and F5-TTS Studio are optional free local engines installed from Setup and require a short reference voice clip."
        )
        self.voice_delivery_box = _combo(
            list(DELIVERY_PROFILES),
            getattr(self.settings, "voice_delivery", "Natural Storyteller"),
        )
        self.voice_delivery_box.setToolTip(
            "Voice Director changes cadence and pause structure without rewriting factual content."
        )
        self.runtime_lock_check = QCheckBox("Measured runtime lock")
        self.runtime_lock_check.setChecked(True)
        self.runtime_lock_check.setToolTip(
            "Synthesizes narration early, measures the real WAV, and performs one focused rewrite if the result misses the requested duration by more than 5%."
        )
        self.visual_qa_v2_check = QCheckBox("Visual QA v2")
        self.visual_qa_v2_check.setChecked(True)
        self.ocr_guard_check = QCheckBox("Reject readable AI text")
        self.ocr_guard_check.setChecked(True)
        self.ocr_guard_check.setToolTip(
            "Uses Tesseract when available, plus built-in composition checks. If Tesseract is not installed, the other Visual QA v2 checks still run."
        )
        self.dynamic_visual_pacing_check = QCheckBox("Dynamic visual pacing")
        self.dynamic_visual_pacing_check.setChecked(True)
        self.dynamic_visual_pacing_check.setToolTip(
            "Raises sparse 45–90 second reels toward roughly one meaningful visual beat every five seconds (maximum 14 scenes)."
        )

        voice_label = QLabel("Voice engine"); voice_label.setObjectName("Hint")
        delivery_label = QLabel("Voice delivery"); delivery_label.setObjectName("Hint")
        grid.addWidget(voice_label, 10, 0)
        grid.addWidget(delivery_label, 10, 1)
        grid.addWidget(self.voice_engine_box, 11, 0)
        grid.addWidget(self.voice_delivery_box, 11, 1)
        grid.addWidget(self.runtime_lock_check, 12, 0)
        grid.addWidget(self.dynamic_visual_pacing_check, 12, 1)
        grid.addWidget(self.visual_qa_v2_check, 13, 0)
        grid.addWidget(self.ocr_guard_check, 13, 1)
        return page

    def setup_page(self):
        page = original_setup_page(self)
        # Extend the existing Voice card rather than creating another setup section.
        for label in page.findChildren(QLabel):
            if label.text() != "Voice":
                continue
            card = label.parentWidget()
            if not card or not card.layout():
                continue
            note = QLabel(
                "Optional Human Touch voices: Chatterbox Nano (CPU-friendly) or F5-TTS Studio. They install into isolated local Python 3.11 environments and download their own model weights on first use."
            )
            note.setObjectName("Hint")
            note.setWordWrap(True)
            chatter = ui.SoftButton("Install Chatterbox Nano (Optional)")
            chatter.clicked.connect(
                lambda: self._run_setup(
                    "Chatterbox Nano installed",
                    lambda p: install_optional_voice_engine(self.settings, "Chatterbox Nano", p),
                )
            )
            f5 = ui.SoftButton("Install F5-TTS Studio (Optional)")
            f5.clicked.connect(
                lambda: self._run_setup(
                    "F5-TTS Studio installed",
                    lambda p: install_optional_voice_engine(self.settings, "F5-TTS Studio", p),
                )
            )
            card.layout().addWidget(note)
            card.layout().addWidget(chatter)
            card.layout().addWidget(f5)
            break
        return page

    def settings_page(self):
        page = original_settings_page(self)
        cards = page.findChildren(ui.Card)
        if not cards:
            return page
        grid = cards[0].layout()
        if not isinstance(grid, QGridLayout):
            return page
        row = grid.rowCount()

        grid.addWidget(QLabel("Natural voice reference WAV"), row, 0)
        ref = QLineEdit(str(getattr(self.settings, "natural_voice_ref", "")))
        self.setting_edits["natural_voice_ref"] = ref
        grid.addWidget(ref, row, 1)
        browse = ui.SoftButton("Browse")
        browse.clicked.connect(lambda: self._browse_file("natural_voice_ref"))
        grid.addWidget(browse, row, 2)
        row += 1

        grid.addWidget(QLabel("Reference transcript (F5-TTS)"), row, 0)
        ref_text = QLineEdit(str(getattr(self.settings, "natural_voice_ref_text", "")))
        ref_text.setPlaceholderText("What the reference voice clip says")
        self.setting_edits["natural_voice_ref_text"] = ref_text
        grid.addWidget(ref_text, row, 1, 1, 2)
        row += 1

        grid.addWidget(QLabel("Tesseract OCR executable (optional)"), row, 0)
        ocr = QLineEdit(str(getattr(self.settings, "ocr_exe", "")))
        self.setting_edits["ocr_exe"] = ocr
        grid.addWidget(ocr, row, 1)
        ocr_browse = ui.SoftButton("Browse")
        ocr_browse.clicked.connect(lambda: self._browse_file("ocr_exe"))
        grid.addWidget(ocr_browse, row, 2)
        return page

    def options(self):
        opts = original_options(self)
        opts.voice_engine = self.voice_engine_box.currentText()
        opts.voice_delivery = self.voice_delivery_box.currentText()
        opts.runtime_lock = self.runtime_lock_check.isChecked()
        opts.visual_qa_v2 = self.visual_qa_v2_check.isChecked()
        opts.ocr_guard = self.ocr_guard_check.isChecked()
        opts.dynamic_visual_pacing = self.dynamic_visual_pacing_check.isChecked()
        if hasattr(self, "soundtrack_box"):
            opts.soundtrack_mode = self.soundtrack_box.currentText()
            opts.music = opts.soundtrack_mode != "Off"
        return opts

    def generate(self):
        self.settings.voice_engine = self.voice_engine_box.currentText()
        self.settings.voice_delivery = self.voice_delivery_box.currentText()
        self.settings.save()
        result = original_generate(self)
        if getattr(self, "worker", None) and self.worker.isRunning() and hasattr(self, "_append_create_log"):
            self._append_create_log(
                f"Human Touch: {self.voice_engine_box.currentText()} • {self.voice_delivery_box.currentText()} • "
                f"runtime lock {'ON' if self.runtime_lock_check.isChecked() else 'OFF'} • "
                f"dynamic pacing {'ON' if self.dynamic_visual_pacing_check.isChecked() else 'OFF'} • "
                f"Visual QA v2 {'ON' if self.visual_qa_v2_check.isChecked() else 'OFF'}"
            )
        return result

    def complete(self, project):
        result = original_complete(self, project)
        bits = [f"{project.actual_seconds:.1f}s actual / {project.target_seconds}s target"]
        if project.voice_engine_used:
            bits.append(f"voice: {project.voice_engine_used} / {project.voice_delivery}")
        if project.runtime_rewrites:
            bits.append(f"runtime rewrite ×{project.runtime_rewrites}")
        if project.visual_qa_summary:
            bits.append(project.visual_qa_summary)
        if project.soundtrack_used:
            bits.append(f"sound: {project.soundtrack_used}")
        self.status_detail.setText("  •  ".join(bits))
        return result

    ui.MainWindow._sidebar = sidebar
    ui.MainWindow._create_page = create_page
    ui.MainWindow._setup_page = setup_page
    ui.MainWindow._settings_page = settings_page
    ui.MainWindow._options = options
    ui.MainWindow._generate = generate
    ui.MainWindow._on_complete = complete
