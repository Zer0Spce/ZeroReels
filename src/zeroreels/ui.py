from __future__ import annotations

from pathlib import Path
import html
import os

from PySide6.QtCore import QEasingCurve, QThread, Qt, QUrl, Signal, QVariantAnimation
from PySide6.QtGui import QColor, QDesktopServices, QFont, QPixmap
from PySide6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QFileDialog,
    QFrame,
    QGraphicsDropShadowEffect,
    QGridLayout,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QListWidget,
    QMainWindow,
    QMessageBox,
    QPlainTextEdit,
    QProgressBar,
    QPushButton,
    QScrollArea,
    QSizePolicy,
    QSpinBox,
    QStackedWidget,
    QVBoxLayout,
    QWidget,
)

from .config import Settings
from .models import GenerationOptions, Project
from .pipeline import Pipeline
from .services import diagnostics

ACCENT = "#63E6BE"
ACCENT_2 = "#74C0FC"
BG = "#0B0F14"
SURFACE = "#111821"
SURFACE_2 = "#17212B"
TEXT = "#F4F7FA"
MUTED = "#8A98A8"
BORDER = "#24303D"


def build_stylesheet() -> str:
    return f"""
    * {{ font-family: 'Segoe UI'; font-size: 10.5pt; }}
    QMainWindow, QWidget {{ background: {BG}; color: {TEXT}; }}
    QLabel#Title {{ font-size: 24pt; font-weight: 800; }}
    QLabel#Subtitle {{ color: {MUTED}; font-size: 10pt; }}
    QLabel#Section {{ font-size: 13pt; font-weight: 700; }}
    QLabel#Badge {{ background: rgba(99,230,190,0.12); color: {ACCENT}; border: 1px solid rgba(99,230,190,0.28); border-radius: 9px; padding: 3px 8px; font-weight: 700; }}
    QFrame#Card {{ background: {SURFACE}; border: 1px solid {BORDER}; border-radius: 16px; }}
    QFrame#Sidebar {{ background: #0D131A; border-right: 1px solid {BORDER}; }}
    QLineEdit, QPlainTextEdit, QComboBox, QSpinBox, QListWidget {{ background: {SURFACE_2}; border: 1px solid {BORDER}; border-radius: 10px; padding: 8px 10px; selection-background-color: {ACCENT}; selection-color: #07110D; }}
    QLineEdit:focus, QPlainTextEdit:focus, QComboBox:focus, QSpinBox:focus {{ border: 1px solid {ACCENT}; }}
    QComboBox::drop-down {{ border: 0; width: 26px; }}
    QCheckBox {{ spacing: 8px; color: #D8E1E9; }}
    QCheckBox::indicator {{ width: 18px; height: 18px; border-radius: 5px; border: 1px solid #425264; background: {SURFACE_2}; }}
    QCheckBox::indicator:checked {{ background: {ACCENT}; border: 1px solid {ACCENT}; }}
    QPushButton {{ background: {SURFACE_2}; border: 1px solid {BORDER}; border-radius: 10px; padding: 9px 14px; font-weight: 650; }}
    QPushButton:hover {{ background: #1D2A36; border-color: #3B5063; }}
    QPushButton:pressed {{ background: #10171F; padding-top: 10px; padding-bottom: 8px; }}
    QPushButton#Primary {{ background: {ACCENT}; color: #07110D; border: 1px solid {ACCENT}; font-weight: 800; }}
    QPushButton#Primary:hover {{ background: #77EBC8; border-color: #9AF2D7; }}
    QPushButton#Danger {{ color: #FF8787; }}
    QPushButton#Nav {{ text-align: left; border: 0; background: transparent; color: {MUTED}; padding: 10px 12px; }}
    QPushButton#Nav:hover {{ background: rgba(255,255,255,0.04); color: {TEXT}; }}
    QPushButton#Nav:checked {{ background: rgba(99,230,190,0.10); color: {ACCENT}; }}
    QProgressBar {{ background: {SURFACE_2}; border: 0; border-radius: 5px; height: 10px; text-align: center; color: transparent; }}
    QProgressBar::chunk {{ background: {ACCENT}; border-radius: 5px; }}
    QScrollBar:vertical {{ background: transparent; width: 10px; margin: 2px; }}
    QScrollBar::handle:vertical {{ background: #334252; border-radius: 4px; min-height: 30px; }}
    QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical {{ height: 0; }}
    """


class SoftButton(QPushButton):
    """Uniform button with a subtle animated shadow on hover."""
    def __init__(self, text: str = "", parent=None):
        super().__init__(text, parent)
        self.shadow = QGraphicsDropShadowEffect(self)
        self.shadow.setColor(QColor(0, 0, 0, 105))
        self.shadow.setOffset(0, 3)
        self.shadow.setBlurRadius(12)
        self.setGraphicsEffect(self.shadow)
        self.anim = QVariantAnimation(self)
        self.anim.setDuration(140)
        self.anim.setEasingCurve(QEasingCurve.OutCubic)
        self.anim.valueChanged.connect(lambda v: self.shadow.setBlurRadius(float(v)))

    def _animate(self, end: float):
        self.anim.stop()
        self.anim.setStartValue(self.shadow.blurRadius())
        self.anim.setEndValue(end)
        self.anim.start()

    def enterEvent(self, event):
        self.shadow.setColor(QColor(99, 230, 190, 60))
        self._animate(23)
        super().enterEvent(event)

    def leaveEvent(self, event):
        self.shadow.setColor(QColor(0, 0, 0, 105))
        self._animate(12)
        super().leaveEvent(event)


class Card(QFrame):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setObjectName("Card")
        shadow = QGraphicsDropShadowEffect(self)
        shadow.setColor(QColor(0, 0, 0, 70))
        shadow.setBlurRadius(24)
        shadow.setOffset(0, 6)
        self.setGraphicsEffect(shadow)


class PipelineThread(QThread):
    progress_changed = Signal(int, str)
    completed = Signal(object)
    failed = Signal(str)

    def __init__(self, pipeline: Pipeline, project: Project, options: GenerationOptions):
        super().__init__()
        self.pipeline = pipeline
        self.project = project
        self.options = options

    def run(self):
        try:
            result = self.pipeline.run(self.project, self.options, self.progress_changed.emit)
            self.completed.emit(result)
        except Exception as exc:
            self.failed.emit(str(exc))


class MainWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.settings = Settings.load()
        self.current_project: Project | None = None
        self.worker: PipelineThread | None = None
        self.setWindowTitle("ZeroReels — Local AI Video Automation")
        self.resize(1320, 840)
        self.setMinimumSize(1100, 700)
        self._build_ui()

    def _build_ui(self):
        root = QWidget()
        outer = QHBoxLayout(root)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.setSpacing(0)
        outer.addWidget(self._sidebar())
        self.pages = QStackedWidget()
        self.create_page = self._create_page()
        self.scenes_page = self._scenes_page()
        self.queue_page = self._queue_page()
        self.settings_page = self._settings_page()
        self.diag_page = self._diagnostics_page()
        for page in [self.create_page, self.scenes_page, self.queue_page, self.settings_page, self.diag_page]:
            self.pages.addWidget(page)
        outer.addWidget(self.pages, 1)
        self.setCentralWidget(root)

    def _sidebar(self) -> QWidget:
        frame = QFrame()
        frame.setObjectName("Sidebar")
        frame.setFixedWidth(220)
        layout = QVBoxLayout(frame)
        layout.setContentsMargins(18, 20, 18, 20)
        layout.setSpacing(6)
        logo = QLabel("ZERO\nREELS")
        logo.setStyleSheet(f"font-size: 18pt; font-weight: 900; color: {TEXT}; line-height: 1.0;")
        layout.addWidget(logo)
        badge = QLabel("v0.3 TEST")
        badge.setObjectName("Badge")
        badge.setMaximumWidth(80)
        layout.addWidget(badge)
        layout.addSpacing(20)
        self.nav_buttons = []
        for i, (label, symbol) in enumerate([
            ("Create", "＋"), ("Scenes", "▦"), ("Queue", "≡"), ("Settings", "⚙"), ("Diagnostics", "●")
        ]):
            btn = QPushButton(f"{symbol}   {label}")
            btn.setObjectName("Nav")
            btn.setCheckable(True)
            btn.clicked.connect(lambda checked=False, idx=i: self._navigate(idx))
            layout.addWidget(btn)
            self.nav_buttons.append(btn)
        self.nav_buttons[0].setChecked(True)
        layout.addStretch(1)
        note = QLabel("LOCAL-FIRST\nNo paid API required")
        note.setObjectName("Subtitle")
        layout.addWidget(note)
        return frame

    def _navigate(self, index: int):
        self.pages.setCurrentIndex(index)
        for i, btn in enumerate(self.nav_buttons):
            btn.setChecked(i == index)
        if index == 1:
            self._refresh_scenes()
        if index == 4:
            self._refresh_diagnostics()

    @staticmethod
    def _page_header(title: str, subtitle: str) -> tuple[QWidget, QVBoxLayout]:
        page = QWidget()
        layout = QVBoxLayout(page)
        layout.setContentsMargins(34, 28, 34, 28)
        layout.setSpacing(18)
        h = QLabel(title)
        h.setObjectName("Title")
        s = QLabel(subtitle)
        s.setObjectName("Subtitle")
        layout.addWidget(h)
        layout.addWidget(s)
        return page, layout

    def _create_page(self) -> QWidget:
        page, layout = self._page_header("Create a Reel", "One idea in. A finished short-form video out.")
        card = Card()
        grid = QGridLayout(card)
        grid.setContentsMargins(22, 22, 22, 22)
        grid.setHorizontalSpacing(16)
        grid.setVerticalSpacing(12)

        grid.addWidget(QLabel("Topic / idea"), 0, 0, 1, 4)
        self.topic = QPlainTextEdit()
        self.topic.setPlaceholderText("Example: A 60-second mystery about an abandoned lighthouse...")
        self.topic.setMaximumHeight(92)
        grid.addWidget(self.topic, 1, 0, 1, 4)

        self.format_box = QComboBox(); self.format_box.addItems(["9:16", "16:9", "1:1"])
        self.style_box = QComboBox(); self.style_box.addItems(["Cinematic Documentary", "Dark Mystery", "Clean Educational", "Fast Social", "Retro Film", "Anime Inspired"])
        self.seconds = QSpinBox(); self.seconds.setRange(15, 300); self.seconds.setValue(60); self.seconds.setSuffix(" sec")
        self.scene_count = QSpinBox(); self.scene_count.setRange(3, 30); self.scene_count.setValue(8)
        for col, (label, widget) in enumerate([("Format", self.format_box), ("Style", self.style_box), ("Length", self.seconds), ("Scenes", self.scene_count)]):
            grid.addWidget(QLabel(label), 2, col)
            grid.addWidget(widget, 3, col)

        self.mock = QCheckBox("Mock Mode — test without AI models"); self.mock.setChecked(True)
        self.full_auto = QCheckBox("Full Auto"); self.full_auto.setChecked(True)
        self.captions = QCheckBox("Captions"); self.captions.setChecked(True)
        self.motion = QCheckBox("Subtle image motion"); self.motion.setChecked(True)
        grid.addWidget(self.mock, 4, 0, 1, 2)
        grid.addWidget(self.full_auto, 4, 2)
        grid.addWidget(self.captions, 5, 0)
        grid.addWidget(self.motion, 5, 1)

        actions = QHBoxLayout()
        self.queue_add = SoftButton("Add to Queue")
        self.queue_add.clicked.connect(self._add_to_queue)
        self.generate = SoftButton("Generate Video")
        self.generate.setObjectName("Primary")
        self.generate.clicked.connect(self._generate)
        actions.addStretch(1)
        actions.addWidget(self.queue_add)
        actions.addWidget(self.generate)
        grid.addLayout(actions, 6, 0, 1, 4)
        layout.addWidget(card)

        status_card = Card()
        status_layout = QVBoxLayout(status_card)
        status_layout.setContentsMargins(20, 18, 20, 18)
        row = QHBoxLayout()
        self.status_dot = QLabel("●")
        self.status_dot.setStyleSheet(f"color:{ACCENT}; font-size:14pt;")
        self.status_text = QLabel("Ready")
        self.status_text.setObjectName("Section")
        row.addWidget(self.status_dot)
        row.addWidget(self.status_text)
        row.addStretch(1)
        self.open_output = SoftButton("Open Output")
        self.open_output.setEnabled(False)
        self.open_output.clicked.connect(self._open_output)
        row.addWidget(self.open_output)
        status_layout.addLayout(row)
        self.progress = QProgressBar(); self.progress.setRange(0, 100); self.progress.setValue(0)
        status_layout.addWidget(self.progress)
        self.status_detail = QLabel("Mock Mode is enabled. Your first run needs no AI models.")
        self.status_detail.setObjectName("Subtitle")
        status_layout.addWidget(self.status_detail)
        layout.addWidget(status_card)
        layout.addStretch(1)
        return page

    def _scenes_page(self) -> QWidget:
        page, layout = self._page_header("Scenes", "Review the generated story beats and visual prompts.")
        self.scenes_scroll = QScrollArea(); self.scenes_scroll.setWidgetResizable(True); self.scenes_scroll.setFrameShape(QFrame.NoFrame)
        self.scene_container = QWidget(); self.scene_layout = QVBoxLayout(self.scene_container); self.scene_layout.setSpacing(12); self.scene_layout.addStretch(1)
        self.scenes_scroll.setWidget(self.scene_container)
        layout.addWidget(self.scenes_scroll, 1)
        return page

    def _queue_page(self) -> QWidget:
        page, layout = self._page_header("Queue", "Line up multiple ideas now; batch execution is the next step after the v0.3 test.")
        card = Card(); box = QVBoxLayout(card); box.setContentsMargins(20, 20, 20, 20)
        self.queue_list = QListWidget(); self.queue_list.setMinimumHeight(280)
        box.addWidget(self.queue_list)
        row = QHBoxLayout(); clear = SoftButton("Clear Queue"); clear.clicked.connect(self.queue_list.clear)
        next_btn = SoftButton("Load Next"); next_btn.setObjectName("Primary"); next_btn.clicked.connect(self._load_next_queue)
        row.addStretch(1); row.addWidget(clear); row.addWidget(next_btn); box.addLayout(row)
        layout.addWidget(card); layout.addStretch(1)
        return page

    def _settings_page(self) -> QWidget:
        page, layout = self._page_header("Local AI Settings", "Connect ZeroReels to tools running on your own PC.")
        card = Card(); grid = QGridLayout(card); grid.setContentsMargins(22, 22, 22, 22); grid.setVerticalSpacing(10)
        fields = [
            ("Ollama URL", "ollama_url"), ("Ollama model", "ollama_model"), ("ComfyUI URL", "comfy_url"),
            ("ComfyUI workflow JSON", "comfy_workflow"), ("Piper executable", "piper_exe"), ("Piper voice model", "piper_model"),
            ("whisper.cpp executable", "whisper_exe"), ("Whisper model", "whisper_model"), ("FFmpeg executable", "ffmpeg_exe"),
        ]
        self.setting_edits = {}
        for row, (label, key) in enumerate(fields):
            grid.addWidget(QLabel(label), row, 0)
            edit = QLineEdit(str(getattr(self.settings, key))); self.setting_edits[key] = edit
            grid.addWidget(edit, row, 1)
        save = SoftButton("Save Settings"); save.setObjectName("Primary"); save.clicked.connect(self._save_settings)
        grid.addWidget(save, len(fields), 1, alignment=Qt.AlignRight)
        layout.addWidget(card); layout.addStretch(1)
        return page

    def _diagnostics_page(self) -> QWidget:
        page, layout = self._page_header("Diagnostics", "See what is ready before switching Mock Mode off.")
        self.diag_card = Card(); self.diag_layout = QVBoxLayout(self.diag_card); self.diag_layout.setContentsMargins(22, 22, 22, 22)
        layout.addWidget(self.diag_card); layout.addStretch(1)
        return page

    def _refresh_diagnostics(self):
        while self.diag_layout.count():
            item = self.diag_layout.takeAt(0)
            if item.widget(): item.widget().deleteLater()
        for label, ok, detail in diagnostics(self.settings):
            row = QLabel(f"{'●' if ok else '○'}  <b>{html.escape(label)}</b>  <span style='color:{MUTED}'>{html.escape(detail)}</span>")
            row.setStyleSheet(f"color: {ACCENT if ok else '#FF8787'}; padding: 7px;")
            self.diag_layout.addWidget(row)

    def _save_settings(self):
        for key, edit in self.setting_edits.items():
            setattr(self.settings, key, edit.text().strip())
        self.settings.save()
        self.status_detail.setText("Settings saved locally.")

    def _make_project(self) -> Project:
        topic = self.topic.toPlainText().strip()
        if not topic:
            raise ValueError("Enter a topic or idea first.")
        return Project(topic=topic, format=self.format_box.currentText(), style=self.style_box.currentText(), target_seconds=self.seconds.value())

    def _options(self) -> GenerationOptions:
        return GenerationOptions(mock_mode=self.mock.isChecked(), full_auto=self.full_auto.isChecked(), captions=self.captions.isChecked(), motion=self.motion.isChecked(), scene_count=self.scene_count.value())

    def _generate(self):
        if self.worker and self.worker.isRunning():
            return
        try:
            project = self._make_project()
        except ValueError as exc:
            QMessageBox.information(self, "ZeroReels", str(exc)); return
        self.generate.setEnabled(False); self.queue_add.setEnabled(False); self.open_output.setEnabled(False)
        self.progress.setValue(1); self.status_text.setText("Starting"); self.status_detail.setText("Preparing the local pipeline...")
        self.worker = PipelineThread(Pipeline(self.settings), project, self._options())
        self.worker.progress_changed.connect(self._on_progress)
        self.worker.completed.connect(self._on_complete)
        self.worker.failed.connect(self._on_failed)
        self.worker.start()

    def _on_progress(self, value: int, text: str):
        self.progress.setValue(value); self.status_text.setText(text); self.status_detail.setText(f"{value}% complete")

    def _on_complete(self, project: Project):
        self.current_project = project; self.generate.setEnabled(True); self.queue_add.setEnabled(True); self.open_output.setEnabled(True)
        self.progress.setValue(100); self.status_text.setText("Video ready"); self.status_detail.setText(project.video_path)
        self._refresh_scenes()

    def _on_failed(self, message: str):
        self.generate.setEnabled(True); self.queue_add.setEnabled(True); self.status_text.setText("Generation stopped"); self.status_detail.setText(message); self.progress.setValue(0)
        QMessageBox.critical(self, "ZeroReels", message)

    def _open_output(self):
        if self.current_project and self.current_project.video_path:
            QDesktopServices.openUrl(QUrl.fromLocalFile(self.current_project.video_path))

    def _refresh_scenes(self):
        while self.scene_layout.count() > 1:
            item = self.scene_layout.takeAt(0)
            if item.widget(): item.widget().deleteLater()
        if not self.current_project or not self.current_project.scenes:
            empty = QLabel("Generate a reel first. Your scenes will appear here."); empty.setObjectName("Subtitle"); self.scene_layout.insertWidget(0, empty); return
        for scene in self.current_project.scenes:
            card = Card(); row = QHBoxLayout(card); row.setContentsMargins(16, 16, 16, 16); row.setSpacing(16)
            preview = QLabel(); preview.setFixedSize(126, 180); preview.setAlignment(Qt.AlignCenter); preview.setStyleSheet(f"background:{SURFACE_2}; border-radius:10px;")
            if scene.image_path and Path(scene.image_path).exists():
                pix = QPixmap(scene.image_path); preview.setPixmap(pix.scaled(preview.size(), Qt.KeepAspectRatioByExpanding, Qt.SmoothTransformation))
            text = QVBoxLayout(); title = QLabel(f"Scene {scene.index:02d}  •  {scene.duration:.1f}s"); title.setObjectName("Section")
            narration = QLabel(scene.narration); narration.setWordWrap(True)
            prompt = QLabel(scene.image_prompt); prompt.setWordWrap(True); prompt.setObjectName("Subtitle")
            text.addWidget(title); text.addWidget(narration); text.addSpacing(5); text.addWidget(prompt); text.addStretch(1)
            row.addWidget(preview); row.addLayout(text, 1)
            self.scene_layout.insertWidget(self.scene_layout.count()-1, card)

    def _add_to_queue(self):
        topic = self.topic.toPlainText().strip()
        if topic:
            self.queue_list.addItem(topic); self.status_detail.setText("Added to queue.")

    def _load_next_queue(self):
        if self.queue_list.count() == 0: return
        item = self.queue_list.takeItem(0); self.topic.setPlainText(item.text()); self._navigate(0)
