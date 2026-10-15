from __future__ import annotations

import re

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QComboBox, QGridLayout, QLabel, QPlainTextEdit, QVBoxLayout

from . import ui
from .setup_tools import pull_ollama_model
from .v080_script import QUALITY_MODEL


def install() -> None:
    original_sidebar = ui.MainWindow._sidebar
    original_create_page = ui.MainWindow._create_page
    original_setup_page = ui.MainWindow._setup_page
    original_make_project = ui.MainWindow._make_project
    original_options = ui.MainWindow._options
    original_generate = ui.MainWindow._generate
    original_complete = ui.MainWindow._on_complete

    def sidebar(self):
        frame = original_sidebar(self)
        for label in frame.findChildren(QLabel):
            if label.text().startswith("v0."):
                label.setText("v0.8 STORY")
                label.setMaximumWidth(118)
                break
        return frame

    def create_page(self):
        page = original_create_page(self)
        scroll = getattr(self, "create_scroll_area", None)
        content = scroll.widget() if scroll is not None else None
        body = content.layout() if content is not None else None
        if not isinstance(body, QVBoxLayout):
            return page

        card = ui.Card()
        card.setObjectName("StoryDirectorCard")
        grid = QGridLayout(card)
        grid.setContentsMargins(20, 18, 20, 18)
        grid.setHorizontalSpacing(14)
        grid.setVerticalSpacing(9)

        title = QLabel("Story Director")
        title.setObjectName("Section")
        subtitle = QLabel(
            "Use ZeroReels' new hook-first writer, paste your finished narration unchanged, or let AI polish your own draft while keeping its facts and intent."
        )
        subtitle.setObjectName("Hint")
        subtitle.setWordWrap(True)
        grid.addWidget(title, 0, 0, 1, 2)
        grid.addWidget(subtitle, 1, 0, 1, 2)

        mode_label = QLabel("Script source")
        mode_label.setObjectName("Hint")
        model_label = QLabel("Writer model")
        model_label.setObjectName("Hint")
        self.script_mode_box = QComboBox()
        self.script_mode_box.addItems(["AI Script", "Custom Script", "AI Polish My Script"])
        self.script_mode_box.setMinimumHeight(38)
        self.script_mode_box.setToolTip(
            "AI Script writes from the topic. Custom Script preserves your narration. AI Polish My Script keeps your facts/meaning but improves hook, rhythm and spoken flow."
        )
        self.script_model_box = QComboBox()
        self.script_model_box.addItems(["Auto Quality", "Qwen3 8B Quality", "Qwen3 4B Fast"])
        self.script_model_box.setMinimumHeight(38)
        self.script_model_box.setToolTip(
            "Auto Quality uses Qwen3 8B when it is installed, otherwise falls back to your current Ollama script model."
        )
        grid.addWidget(mode_label, 2, 0)
        grid.addWidget(model_label, 2, 1)
        grid.addWidget(self.script_mode_box, 3, 0)
        grid.addWidget(self.script_model_box, 3, 1)

        self.custom_script_label = QLabel("Your narration")
        self.custom_script_label.setObjectName("Hint")
        self.custom_script_editor = QPlainTextEdit()
        self.custom_script_editor.setMinimumHeight(150)
        self.custom_script_editor.setMaximumHeight(240)
        self.custom_script_editor.setPlaceholderText(
            "Paste your complete narration here. In Custom Script mode ZeroReels will keep your wording and only split it into visual beats."
        )
        self.custom_script_note = QLabel(
            "Custom Script: your wording is preserved. AI Polish My Script: Story Director improves the hook and spoken flow without intentionally adding new facts."
        )
        self.custom_script_note.setObjectName("Hint")
        self.custom_script_note.setWordWrap(True)
        grid.addWidget(self.custom_script_label, 4, 0, 1, 2)
        grid.addWidget(self.custom_script_editor, 5, 0, 1, 2)
        grid.addWidget(self.custom_script_note, 6, 0, 1, 2)

        def refresh_mode(value: str) -> None:
            enabled = value in {"Custom Script", "AI Polish My Script"}
            self.custom_script_editor.setEnabled(enabled)
            self.custom_script_label.setEnabled(enabled)
            self.custom_script_note.setEnabled(enabled)
            if value == "AI Script":
                self.custom_script_editor.setPlaceholderText(
                    "Switch Script source to Custom Script or AI Polish My Script to paste your narration."
                )
            elif value == "Custom Script":
                self.custom_script_editor.setPlaceholderText(
                    "Paste your final narration. ZeroReels will preserve it and automatically create visual beats, captions and voice timing."
                )
            else:
                self.custom_script_editor.setPlaceholderText(
                    "Paste a rough draft. Story Director will keep the facts and intent, but rewrite it with a stronger hook and more natural spoken rhythm."
                )

        self.script_mode_box.currentTextChanged.connect(refresh_mode)
        refresh_mode(self.script_mode_box.currentText())

        body.insertWidget(1, card)
        card.setMinimumHeight(285)
        self.story_director_card = card
        return page

    def setup_page(self):
        page = original_setup_page(self)
        for label in page.findChildren(QLabel):
            if label.text() != "Script AI":
                continue
            card = label.parentWidget()
            if not card or not card.layout():
                continue
            note = QLabel(
                "Optional quality writer: Qwen3 8B gives Story Director more natural hooks and prose. Auto Quality uses it when installed and falls back to the current model when it is not."
            )
            note.setObjectName("Hint")
            note.setWordWrap(True)
            button = ui.SoftButton("Download Quality Writer — Qwen3 8B (Optional)")
            button.clicked.connect(
                lambda checked=False: self._run_setup(
                    "Qwen3 8B quality writer ready",
                    lambda progress, log: pull_ollama_model(QUALITY_MODEL, progress, log),
                )
            )
            card.layout().addWidget(note)
            card.layout().addWidget(button)
            break
        return page

    def make_project(self):
        mode = self.script_mode_box.currentText() if hasattr(self, "script_mode_box") else "AI Script"
        custom = self.custom_script_editor.toPlainText().strip() if hasattr(self, "custom_script_editor") else ""
        if mode in {"Custom Script", "AI Polish My Script"} and not custom:
            raise ValueError("Paste your narration in Story Director first.")

        # Topic becomes optional for a pasted script. Use its opening as a private project slug/context
        # if the user intentionally leaves Topic blank, then restore the UI field afterwards.
        restore_topic = None
        if mode in {"Custom Script", "AI Polish My Script"} and not self.topic.toPlainText().strip():
            words = re.findall(r"\S+", custom)
            derived = " ".join(words[:12]).strip(" .,!?:;-") or "Custom narration"
            restore_topic = ""
            self.topic.setPlainText(derived)
        try:
            project = original_make_project(self)
        finally:
            if restore_topic is not None:
                self.topic.setPlainText(restore_topic)

        project.script_mode = mode
        project.custom_script = custom
        project.script_model_mode = self.script_model_box.currentText() if hasattr(self, "script_model_box") else "Auto Quality"
        return project

    def options(self):
        opts = original_options(self)
        opts.script_mode = self.script_mode_box.currentText()
        opts.script_model_mode = self.script_model_box.currentText()
        return opts

    def generate(self):
        result = original_generate(self)
        if getattr(self, "worker", None) and self.worker.isRunning() and hasattr(self, "_append_create_log"):
            mode = self.script_mode_box.currentText()
            model = self.script_model_box.currentText()
            self._append_create_log(f"Story Director v2: {mode} • {model}")
            if mode == "Custom Script":
                self._append_create_log("Custom narration will be preserved; AI is used only for beat/visual planning.")
            elif mode == "AI Polish My Script":
                self._append_create_log("Your draft will be humanized for hook, spoken rhythm and retention before visual planning.")
        return result

    def complete(self, project):
        result = original_complete(self, project)
        if hasattr(self, "status_detail"):
            detail = self.status_detail.text()
            additions = []
            if getattr(project, "script_model_used", ""):
                additions.append(f"writer: {project.script_model_used}")
            if getattr(project, "script_quality_summary", ""):
                additions.append(project.script_quality_summary)
            if additions:
                self.status_detail.setText((detail + "  •  " + "  •  ".join(additions)).strip(" •"))
        return result

    ui.MainWindow._sidebar = sidebar
    ui.MainWindow._create_page = create_page
    ui.MainWindow._setup_page = setup_page
    ui.MainWindow._make_project = make_project
    ui.MainWindow._options = options
    ui.MainWindow._generate = generate
    ui.MainWindow._on_complete = complete
