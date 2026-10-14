from __future__ import annotations

from pathlib import Path
import html

from PySide6.QtCore import QEasingCurve, QThread, Qt, QUrl, Signal, QVariantAnimation
from PySide6.QtGui import QColor, QDesktopServices, QPixmap
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
    QSpinBox,
    QStackedWidget,
    QVBoxLayout,
    QWidget,
)

from .config import Settings, detect_comfy_root
from .models import GenerationOptions, Project
from .pipeline import Pipeline
from .services import diagnostics
from .setup_tools import (
    download_flux_models,
    download_kokoro_models,
    gpu_summary,
    install_comfyui,
    install_ollama,
    pull_ollama_model,
)

ACCENT = "#63E6BE"
ACCENT_HOVER = "#7AEDD0"
BG = "#090D12"
SIDEBAR = "#0D131A"
SURFACE = "#111821"
SURFACE_2 = "#17212B"
TEXT = "#F4F7FA"
MUTED = "#8A98A8"
BORDER = "#24303D"
DANGER = "#FF8787"
WARNING = "#FFD166"


def build_stylesheet() -> str:
    return f"""
    * {{ font-family: 'Segoe UI'; font-size: 10.5pt; }}
    QMainWindow, QWidget {{ background: {BG}; color: {TEXT}; }}
    QLabel#Title {{ font-size: 24pt; font-weight: 800; }}
    QLabel#Subtitle {{ color: {MUTED}; font-size: 10pt; }}
    QLabel#Section {{ font-size: 13pt; font-weight: 700; }}
    QLabel#Badge {{ background: rgba(99,230,190,0.12); color: {ACCENT}; border: 1px solid rgba(99,230,190,0.28); border-radius: 9px; padding: 3px 8px; font-weight: 700; }}
    QLabel#Hint {{ color: {MUTED}; font-size: 9.5pt; }}
    QFrame#Card {{ background: {SURFACE}; border: 1px solid {BORDER}; border-radius: 16px; }}
    QFrame#Sidebar {{ background: {SIDEBAR}; border-right: 1px solid {BORDER}; }}
    QLineEdit, QPlainTextEdit, QComboBox, QSpinBox, QListWidget {{ background: {SURFACE_2}; border: 1px solid {BORDER}; border-radius: 10px; padding: 8px 10px; selection-background-color: {ACCENT}; selection-color: #07110D; }}
    QLineEdit:focus, QPlainTextEdit:focus, QComboBox:focus, QSpinBox:focus {{ border: 1px solid {ACCENT}; }}
    QComboBox::drop-down {{ border: 0; width: 26px; }}
    QCheckBox {{ spacing: 8px; color: #D8E1E9; }}
    QCheckBox::indicator {{ width: 18px; height: 18px; border-radius: 5px; border: 1px solid #425264; background: {SURFACE_2}; }}
    QCheckBox::indicator:checked {{ background: {ACCENT}; border: 1px solid {ACCENT}; }}
    QPushButton {{ background: {SURFACE_2}; border: 1px solid {BORDER}; border-radius: 10px; padding: 9px 14px; font-weight: 650; }}
    QPushButton:hover {{ background: #1D2A36; border-color: #3B5063; }}
    QPushButton:pressed {{ background: #10171F; padding-top: 10px; padding-bottom: 8px; }}
    QPushButton:disabled {{ color: #5F6B77; background: #111820; border-color: #1B2530; }}
    QPushButton#Primary {{ background: {ACCENT}; color: #07110D; border: 1px solid {ACCENT}; font-weight: 800; }}
    QPushButton#Primary:hover {{ background: {ACCENT_HOVER}; border-color: #A2F4DD; }}
    QPushButton#SecondaryAccent {{ color: {ACCENT}; border-color: rgba(99,230,190,0.45); }}
    QPushButton#Nav {{ text-align: left; border: 0; background: transparent; color: {MUTED}; padding: 10px 12px; }}
    QPushButton#Nav:hover {{ background: rgba(255,255,255,0.04); color: {TEXT}; }}
    QPushButton#Nav:checked {{ background: rgba(99,230,190,0.10); color: {ACCENT}; }}
    QProgressBar {{ background: {SURFACE_2}; border: 0; border-radius: 5px; height: 10px; text-align: center; color: transparent; }}
    QProgressBar::chunk {{ background: {ACCENT}; border-radius: 5px; }}
    QScrollArea {{ border: 0; }}
    QScrollBar:vertical {{ background: transparent; width: 10px; margin: 2px; }}
    QScrollBar::handle:vertical {{ background: #334252; border-radius: 4px; min-height: 30px; }}
    QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical {{ height: 0; }}
    """


class SoftButton(QPushButton):
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
        self.anim.valueChanged.connect(lambda value: self.shadow.setBlurRadius(float(value)))

    def _animate(self, end: float) -> None:
        self.anim.stop()
        self.anim.setStartValue(self.shadow.blurRadius())
        self.anim.setEndValue(end)
        self.anim.start()

    def enterEvent(self, event):
        if self.isEnabled():
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


class SetupThread(QThread):
    progress_changed = Signal(int, str)
    completed = Signal(str)
    failed = Signal(str)

    def __init__(self, label: str, action):
        super().__init__()
        self.label = label
        self.action = action

    def run(self):
        try:
            try:
                self.action(self.progress_changed.emit)
            except TypeError:
                self.action()
            self.completed.emit(self.label)
        except Exception as exc:
            self.failed.emit(str(exc))


class MainWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.settings = Settings.load()
        self.current_project: Project | None = None
        self.worker: PipelineThread | None = None
        self.setup_worker: SetupThread | None = None
        self.setWindowTitle("ZeroReels — Local AI Video Automation")
        self.resize(1360, 860)
        self.setMinimumSize(1120, 720)
        self._build_ui()

    def _build_ui(self):
        root = QWidget()
        outer = QHBoxLayout(root)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.setSpacing(0)
        outer.addWidget(self._sidebar())

        self.pages = QStackedWidget()
        for page in [
            self._create_page(),
            self._scenes_page(),
            self._queue_page(),
            self._setup_page(),
            self._settings_page(),
            self._diagnostics_page(),
        ]:
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
        logo.setStyleSheet(f"font-size:18pt; font-weight:900; color:{TEXT};")
        layout.addWidget(logo)
        badge = QLabel("v0.4 REAL")
        badge.setObjectName("Badge")
        badge.setMaximumWidth(88)
        layout.addWidget(badge)
        layout.addSpacing(20)

        self.nav_buttons: list[QPushButton] = []
        items = [
            ("Create", "＋"),
            ("Scenes", "▦"),
            ("Queue", "≡"),
            ("Setup", "↓"),
            ("Settings", "⚙"),
            ("Diagnostics", "●"),
        ]
        for index, (label, symbol) in enumerate(items):
            btn = QPushButton(f"{symbol}   {label}")
            btn.setObjectName("Nav")
            btn.setCheckable(True)
            btn.clicked.connect(lambda checked=False, idx=index: self._navigate(idx))
            layout.addWidget(btn)
            self.nav_buttons.append(btn)
        self.nav_buttons[0].setChecked(True)
        layout.addStretch(1)
        footer = QLabel("WINDOWS 10/11\nLocal • Free • Private")
        footer.setObjectName("Subtitle")
        layout.addWidget(footer)
        return frame

    def _navigate(self, index: int):
        self.pages.setCurrentIndex(index)
        for i, button in enumerate(self.nav_buttons):
            button.setChecked(i == index)
        if index == 1:
            self._refresh_scenes()
        elif index in (3, 5):
            self._refresh_diagnostics()
            if index == 3:
                self._refresh_setup_summary()

    @staticmethod
    def _page(title: str, subtitle: str) -> tuple[QWidget, QVBoxLayout]:
        page = QWidget()
        layout = QVBoxLayout(page)
        layout.setContentsMargins(34, 28, 34, 28)
        layout.setSpacing(18)
        heading = QLabel(title)
        heading.setObjectName("Title")
        sub = QLabel(subtitle)
        sub.setObjectName("Subtitle")
        sub.setWordWrap(True)
        layout.addWidget(heading)
        layout.addWidget(sub)
        return page, layout

    def _create_page(self) -> QWidget:
        page, layout = self._page("Create a Reel", "One idea in. ZeroReels handles the local script, images, voice, captions, motion, and MP4 render.")
        card = Card()
        grid = QGridLayout(card)
        grid.setContentsMargins(22, 22, 22, 22)
        grid.setHorizontalSpacing(16)
        grid.setVerticalSpacing(12)

        grid.addWidget(QLabel("Topic / idea"), 0, 0, 1, 4)
        self.topic = QPlainTextEdit()
        self.topic.setPlaceholderText("Example: The strange story of a lighthouse that suddenly went dark...")
        self.topic.setMaximumHeight(96)
        grid.addWidget(self.topic, 1, 0, 1, 4)

        self.format_box = QComboBox(); self.format_box.addItems(["9:16", "16:9", "1:1"])
        self.style_box = QComboBox(); self.style_box.addItems([
            "Cinematic Documentary", "Dark Mystery", "Clean Educational",
            "Fast Social", "Retro Film", "Anime Inspired",
        ])
        self.seconds = QSpinBox(); self.seconds.setRange(15, 300); self.seconds.setValue(60); self.seconds.setSuffix(" sec")
        self.scene_count = QSpinBox(); self.scene_count.setRange(3, 24); self.scene_count.setValue(8)
        for col, (label, widget) in enumerate([
            ("Format", self.format_box), ("Style", self.style_box),
            ("Target length", self.seconds), ("Scenes", self.scene_count),
        ]):
            grid.addWidget(QLabel(label), 2, col)
            grid.addWidget(widget, 3, col)

        grid.addWidget(QLabel("Narrator voice"), 4, 0)
        self.voice_box = QComboBox()
        self.voice_box.addItems(["af_heart", "af_sarah", "af_bella", "am_adam", "am_michael", "bf_emma", "bm_george"])
        if self.settings.kokoro_voice not in [self.voice_box.itemText(i) for i in range(self.voice_box.count())]:
            self.voice_box.addItem(self.settings.kokoro_voice)
        self.voice_box.setCurrentText(self.settings.kokoro_voice)
        grid.addWidget(self.voice_box, 4, 1)

        self.test_mode = QCheckBox("Test Mode — no AI models")
        self.test_mode.setChecked(False)
        self.captions = QCheckBox("Burn captions into video"); self.captions.setChecked(True)
        self.motion = QCheckBox("Subtle image motion"); self.motion.setChecked(True)
        self.transitions = QCheckBox("Soft fade transitions"); self.transitions.setChecked(True)
        grid.addWidget(self.test_mode, 5, 0, 1, 2)
        grid.addWidget(self.captions, 5, 2, 1, 2)
        grid.addWidget(self.motion, 6, 0, 1, 2)
        grid.addWidget(self.transitions, 6, 2, 1, 2)

        actions = QHBoxLayout()
        self.queue_add = SoftButton("Add to Queue")
        self.queue_add.clicked.connect(self._add_to_queue)
        setup_btn = SoftButton("Check Setup")
        setup_btn.clicked.connect(lambda: self._navigate(3))
        self.generate = SoftButton("Generate Video")
        self.generate.setObjectName("Primary")
        self.generate.clicked.connect(self._generate)
        actions.addStretch(1)
        actions.addWidget(setup_btn)
        actions.addWidget(self.queue_add)
        actions.addWidget(self.generate)
        grid.addLayout(actions, 7, 0, 1, 4)
        layout.addWidget(card)

        status_card = Card()
        status = QVBoxLayout(status_card)
        status.setContentsMargins(20, 18, 20, 18)
        row = QHBoxLayout()
        self.status_dot = QLabel("●")
        self.status_dot.setStyleSheet(f"color:{ACCENT}; font-size:14pt;")
        self.status_text = QLabel("Ready")
        self.status_text.setObjectName("Section")
        row.addWidget(self.status_dot); row.addWidget(self.status_text); row.addStretch(1)
        self.open_folder = SoftButton("Open Project Folder")
        self.open_folder.setEnabled(False)
        self.open_folder.clicked.connect(self._open_project_folder)
        self.open_output = SoftButton("Play Output")
        self.open_output.setObjectName("SecondaryAccent")
        self.open_output.setEnabled(False)
        self.open_output.clicked.connect(self._open_output)
        row.addWidget(self.open_folder); row.addWidget(self.open_output)
        status.addLayout(row)
        self.progress = QProgressBar(); self.progress.setRange(0, 100); self.progress.setValue(0)
        status.addWidget(self.progress)
        self.status_detail = QLabel("Real generation is enabled. Use Setup once before your first AI run.")
        self.status_detail.setObjectName("Subtitle")
        self.status_detail.setWordWrap(True)
        status.addWidget(self.status_detail)
        layout.addWidget(status_card)
        layout.addStretch(1)
        return page

    def _scenes_page(self) -> QWidget:
        page, layout = self._page("Scenes", "Preview the generated images, narration, timing, and visual prompts used in your current project.")
        self.scenes_scroll = QScrollArea(); self.scenes_scroll.setWidgetResizable(True)
        self.scene_container = QWidget(); self.scene_layout = QVBoxLayout(self.scene_container); self.scene_layout.setSpacing(12); self.scene_layout.addStretch(1)
        self.scenes_scroll.setWidget(self.scene_container)
        layout.addWidget(self.scenes_scroll, 1)
        return page

    def _queue_page(self) -> QWidget:
        page, layout = self._page("Queue", "Keep a list of ideas and load the next one into Create. Automatic unattended batch generation comes after the real pipeline is proven on your PC.")
        card = Card(); box = QVBoxLayout(card); box.setContentsMargins(20, 20, 20, 20)
        self.queue_list = QListWidget(); self.queue_list.setMinimumHeight(280)
        box.addWidget(self.queue_list)
        row = QHBoxLayout()
        clear = SoftButton("Clear Queue"); clear.clicked.connect(self.queue_list.clear)
        load = SoftButton("Load Next"); load.setObjectName("Primary"); load.clicked.connect(self._load_next_queue)
        row.addStretch(1); row.addWidget(clear); row.addWidget(load)
        box.addLayout(row)
        layout.addWidget(card); layout.addStretch(1)
        return page

    def _setup_page(self) -> QWidget:
        page, layout = self._page("First-Time Setup", "Everything stays local and free. Install the engines once, then ZeroReels can generate videos without paid APIs.")

        summary = Card(); sum_box = QVBoxLayout(summary); sum_box.setContentsMargins(20, 18, 20, 18)
        row = QHBoxLayout()
        title = QLabel("System readiness"); title.setObjectName("Section")
        row.addWidget(title); row.addStretch(1)
        refresh = SoftButton("Refresh"); refresh.clicked.connect(self._refresh_setup_summary)
        row.addWidget(refresh); sum_box.addLayout(row)
        self.gpu_label = QLabel(gpu_summary()); self.gpu_label.setObjectName("Subtitle"); sum_box.addWidget(self.gpu_label)
        self.setup_summary = QLabel("Checking local components..."); self.setup_summary.setWordWrap(True); sum_box.addWidget(self.setup_summary)
        layout.addWidget(summary)

        grid_wrap = QWidget(); grid = QGridLayout(grid_wrap); grid.setContentsMargins(0, 0, 0, 0); grid.setSpacing(14)
        self.setup_cards = []

        card1, body1 = self._setup_card("1", "Script AI", "Ollama + Qwen run the script and scene planner entirely on your PC.")
        install_o = SoftButton("Install Ollama"); install_o.clicked.connect(lambda: self._run_setup("Ollama installed", lambda p: install_ollama()))
        pull = SoftButton("Download Script Model"); pull.setObjectName("Primary"); pull.clicked.connect(lambda: self._run_setup("Script model ready", lambda p: pull_ollama_model(self.settings.ollama_model, p)))
        body1.addWidget(install_o); body1.addWidget(pull)
        grid.addWidget(card1, 0, 0)

        card2, body2 = self._setup_card("2", "Image AI", "ComfyUI Desktop + FLUX.2 Klein 4B generate every scene locally. Model download is large (~15 GB+).")
        install_c = SoftButton("Install ComfyUI Desktop"); install_c.clicked.connect(lambda: self._run_setup("ComfyUI installed", lambda p: install_comfyui()))
        detect = SoftButton("Detect / Select Data Folder"); detect.clicked.connect(self._select_comfy_root)
        flux = SoftButton("Download FLUX.2 Model Pack"); flux.setObjectName("Primary"); flux.clicked.connect(self._download_flux)
        body2.addWidget(install_c); body2.addWidget(detect); body2.addWidget(flux)
        grid.addWidget(card2, 0, 1)

        card3, body3 = self._setup_card("3", "Voice", "Kokoro generates natural narration locally. ZeroReels includes the engine; download the compact local model and voice pack once.")
        voice = SoftButton("Download Kokoro Voice Files"); voice.setObjectName("Primary"); voice.clicked.connect(lambda: self._run_setup("Voice ready", lambda p: download_kokoro_models(self.settings, p)))
        body3.addWidget(voice)
        grid.addWidget(card3, 1, 0)

        card4, body4 = self._setup_card("4", "Finish", "Open Ollama and ComfyUI, refresh diagnostics, then generate from the Create page.")
        diag = SoftButton("Open Diagnostics"); diag.setObjectName("Primary"); diag.clicked.connect(lambda: self._navigate(5))
        body4.addWidget(diag)
        grid.addWidget(card4, 1, 1)

        grid.setColumnStretch(0, 1); grid.setColumnStretch(1, 1)
        layout.addWidget(grid_wrap)

        progress_card = Card(); pb = QVBoxLayout(progress_card); pb.setContentsMargins(20, 16, 20, 16)
        self.setup_progress = QProgressBar(); self.setup_progress.setRange(0, 100); self.setup_progress.setValue(0)
        self.setup_status = QLabel("No setup task running."); self.setup_status.setObjectName("Subtitle")
        pb.addWidget(self.setup_progress); pb.addWidget(self.setup_status)
        layout.addWidget(progress_card)
        layout.addStretch(1)
        return page

    def _setup_card(self, number: str, title: str, description: str) -> tuple[Card, QVBoxLayout]:
        card = Card(); box = QVBoxLayout(card); box.setContentsMargins(18, 18, 18, 18); box.setSpacing(10)
        head = QHBoxLayout(); badge = QLabel(number); badge.setObjectName("Badge"); badge.setMaximumWidth(28)
        label = QLabel(title); label.setObjectName("Section")
        head.addWidget(badge); head.addWidget(label); head.addStretch(1); box.addLayout(head)
        desc = QLabel(description); desc.setObjectName("Subtitle"); desc.setWordWrap(True); box.addWidget(desc); box.addStretch(1)
        return card, box

    def _settings_page(self) -> QWidget:
        page, layout = self._page("Settings", "Advanced local engine settings. Most users can leave these defaults alone after completing Setup.")
        scroll = QScrollArea(); scroll.setWidgetResizable(True)
        container = QWidget(); outer = QVBoxLayout(container); outer.setContentsMargins(0, 0, 10, 0)
        card = Card(); grid = QGridLayout(card); grid.setContentsMargins(22, 22, 22, 22); grid.setHorizontalSpacing(14); grid.setVerticalSpacing(10)
        fields = [
            ("Ollama URL", "ollama_url"), ("Ollama model", "ollama_model"),
            ("ComfyUI URL", "comfy_url"), ("ComfyUI data folder", "comfy_root"),
            ("FLUX diffusion model", "comfy_unet"), ("FLUX text encoder", "comfy_clip"), ("FLUX VAE", "comfy_vae"),
            ("Kokoro model", "kokoro_model_path"), ("Kokoro voice pack", "kokoro_voices_path"),
            ("Kokoro voice", "kokoro_voice"), ("Kokoro language", "kokoro_lang"),
            ("FFmpeg executable (optional)", "ffmpeg_exe"), ("Music folder (future)", "music_dir"),
        ]
        self.setting_edits: dict[str, QLineEdit] = {}
        for row, (label, key) in enumerate(fields):
            grid.addWidget(QLabel(label), row, 0)
            edit = QLineEdit(str(getattr(self.settings, key))); self.setting_edits[key] = edit
            grid.addWidget(edit, row, 1)
            if key in {"comfy_root", "music_dir"}:
                browse = SoftButton("Browse")
                browse.clicked.connect(lambda checked=False, k=key: self._browse_folder(k))
                grid.addWidget(browse, row, 2)
            elif key in {"kokoro_model_path", "kokoro_voices_path"}:
                browse = SoftButton("Browse")
                browse.clicked.connect(lambda checked=False, k=key: self._browse_file(k))
                grid.addWidget(browse, row, 2)
        row = len(fields)
        grid.addWidget(QLabel("Voice speed"), row, 0)
        self.voice_speed_box = QSpinBox(); self.voice_speed_box.setRange(70, 130); self.voice_speed_box.setValue(int(self.settings.kokoro_speed * 100)); self.voice_speed_box.setSuffix("%")
        grid.addWidget(self.voice_speed_box, row, 1)
        row += 1
        grid.addWidget(QLabel("Transition length"), row, 0)
        self.transition_box = QSpinBox(); self.transition_box.setRange(10, 80); self.transition_box.setValue(int(self.settings.transition_seconds * 100)); self.transition_box.setSuffix(" /100 sec")
        grid.addWidget(self.transition_box, row, 1)
        save = SoftButton("Save Settings"); save.setObjectName("Primary"); save.clicked.connect(self._save_settings)
        grid.addWidget(save, row + 1, 1, alignment=Qt.AlignRight)
        outer.addWidget(card); outer.addStretch(1); scroll.setWidget(container); layout.addWidget(scroll, 1)
        return page

    def _diagnostics_page(self) -> QWidget:
        page, layout = self._page("Diagnostics", "Live checks for the components ZeroReels needs for a real local generation run.")
        top = QHBoxLayout(); self.diag_gpu = QLabel(gpu_summary()); self.diag_gpu.setObjectName("Subtitle"); top.addWidget(self.diag_gpu); top.addStretch(1)
        refresh = SoftButton("Run Checks"); refresh.clicked.connect(self._refresh_diagnostics); top.addWidget(refresh); layout.addLayout(top)
        self.diag_card = Card(); self.diag_layout = QVBoxLayout(self.diag_card); self.diag_layout.setContentsMargins(22, 22, 22, 22); self.diag_layout.setSpacing(5)
        layout.addWidget(self.diag_card); layout.addStretch(1)
        return page

    def _refresh_diagnostics(self):
        if not hasattr(self, "diag_layout"):
            return
        while self.diag_layout.count():
            item = self.diag_layout.takeAt(0)
            if item.widget(): item.widget().deleteLater()
        for label, ok, detail in diagnostics(self.settings):
            row = QLabel(f"{'●' if ok else '○'}  <b>{html.escape(label)}</b>  <span style='color:{MUTED}'>{html.escape(detail)}</span>")
            row.setWordWrap(True)
            row.setStyleSheet(f"color:{ACCENT if ok else DANGER}; padding:7px;")
            self.diag_layout.addWidget(row)

    def _refresh_setup_summary(self):
        if not hasattr(self, "setup_summary"):
            return
        rows = diagnostics(self.settings)
        ready = sum(1 for _, ok, _ in rows if ok)
        total = len(rows)
        missing = [label for label, ok, _ in rows if not ok]
        if not missing:
            text = f"<span style='color:{ACCENT}'><b>READY</b></span> — all {total} checks passed."
        else:
            text = f"<b>{ready}/{total} ready.</b> Missing: {html.escape(', '.join(missing))}"
        if self.settings.comfy_root:
            text += f"<br><span style='color:{MUTED}'>ComfyUI data: {html.escape(self.settings.comfy_root)}</span>"
        self.setup_summary.setText(text)
        self.gpu_label.setText(gpu_summary())

    def _run_setup(self, label: str, action):
        if self.setup_worker and self.setup_worker.isRunning():
            return
        self.setup_progress.setValue(2); self.setup_status.setText("Starting...")
        self.setup_worker = SetupThread(label, action)
        self.setup_worker.progress_changed.connect(lambda value, text: (self.setup_progress.setValue(value), self.setup_status.setText(text)))
        self.setup_worker.completed.connect(self._setup_complete)
        self.setup_worker.failed.connect(self._setup_failed)
        self.setup_worker.start()

    def _setup_complete(self, label: str):
        self.setup_progress.setValue(100); self.setup_status.setText(label)
        self._refresh_setup_summary(); self._refresh_diagnostics()

    def _setup_failed(self, message: str):
        self.setup_progress.setValue(0); self.setup_status.setText(message)
        QMessageBox.critical(self, "ZeroReels Setup", message)

    def _download_flux(self):
        root = self.settings.comfy_root or (str(detect_comfy_root()) if detect_comfy_root() else "")
        if not root:
            self._select_comfy_root()
            root = self.settings.comfy_root
        if not root:
            return
        answer = QMessageBox.question(
            self,
            "Download FLUX.2 Klein",
            "The local image model pack is large (roughly 15 GB+). Download it into your selected ComfyUI data folder now?",
            QMessageBox.Yes | QMessageBox.No,
            QMessageBox.Yes,
        )
        if answer == QMessageBox.Yes:
            self._run_setup("FLUX.2 model pack ready", lambda p: download_flux_models(self.settings, p))

    def _select_comfy_root(self):
        detected = detect_comfy_root()
        start = str(detected or Path.home())
        folder = QFileDialog.getExistingDirectory(self, "Select ComfyUI data folder (the folder containing models)", start)
        if folder:
            root = Path(folder)
            if not (root / "models").exists():
                QMessageBox.warning(self, "ZeroReels", "That folder does not contain a 'models' folder. Select the ComfyUI data/base folder.")
                return
            self.settings.comfy_root = folder
            self.settings.save()
            if hasattr(self, "setting_edits") and "comfy_root" in self.setting_edits:
                self.setting_edits["comfy_root"].setText(folder)
            self._refresh_setup_summary()

    def _browse_folder(self, key: str):
        current = self.setting_edits[key].text().strip() or str(Path.home())
        folder = QFileDialog.getExistingDirectory(self, "Select folder", current)
        if folder:
            self.setting_edits[key].setText(folder)

    def _browse_file(self, key: str):
        current = self.setting_edits[key].text().strip() or str(Path.home())
        filename, _ = QFileDialog.getOpenFileName(self, "Select file", current, "All files (*.*)")
        if filename:
            self.setting_edits[key].setText(filename)

    def _save_settings(self):
        for key, edit in self.setting_edits.items():
            setattr(self.settings, key, edit.text().strip())
        self.settings.kokoro_speed = self.voice_speed_box.value() / 100.0
        self.settings.transition_seconds = self.transition_box.value() / 100.0
        if hasattr(self, "voice_box"):
            self.voice_box.setCurrentText(self.settings.kokoro_voice)
        self.settings.save()
        self.status_detail.setText("Settings saved locally.")
        self._refresh_diagnostics(); self._refresh_setup_summary()

    def _make_project(self) -> Project:
        topic = self.topic.toPlainText().strip()
        if not topic:
            raise ValueError("Enter a topic or idea first.")
        self.settings.kokoro_voice = self.voice_box.currentText()
        self.settings.save()
        return Project(
            topic=topic,
            format=self.format_box.currentText(),
            style=self.style_box.currentText(),
            target_seconds=self.seconds.value(),
            voice=self.voice_box.currentText(),
        )

    def _options(self) -> GenerationOptions:
        return GenerationOptions(
            mock_mode=self.test_mode.isChecked(),
            full_auto=True,
            captions=self.captions.isChecked(),
            motion=self.motion.isChecked(),
            transitions=self.transitions.isChecked(),
            scene_count=self.scene_count.value(),
        )

    def _generate(self):
        if self.worker and self.worker.isRunning():
            return
        try:
            project = self._make_project()
        except ValueError as exc:
            QMessageBox.information(self, "ZeroReels", str(exc)); return
        self.generate.setEnabled(False); self.queue_add.setEnabled(False)
        self.open_output.setEnabled(False); self.open_folder.setEnabled(False)
        self.progress.setValue(1); self.status_text.setText("Starting"); self.status_detail.setText("Preparing local pipeline...")
        self.worker = PipelineThread(Pipeline(self.settings), project, self._options())
        self.worker.progress_changed.connect(self._on_progress)
        self.worker.completed.connect(self._on_complete)
        self.worker.failed.connect(self._on_failed)
        self.worker.start()

    def _on_progress(self, value: int, text: str):
        self.progress.setValue(value); self.status_text.setText(text); self.status_detail.setText(f"{value}% complete")

    def _on_complete(self, project: Project):
        self.current_project = project
        self.generate.setEnabled(True); self.queue_add.setEnabled(True)
        self.open_output.setEnabled(True); self.open_folder.setEnabled(True)
        self.progress.setValue(100); self.status_text.setText("Video ready")
        caption_note = "Captions burned in" if project.captions_burned else ("SRT saved beside video" if project.captions_path else "No captions")
        self.status_detail.setText(f"{project.video_path}  •  {caption_note}")
        self._refresh_scenes()

    def _on_failed(self, message: str):
        self.generate.setEnabled(True); self.queue_add.setEnabled(True)
        self.status_text.setText("Generation stopped"); self.status_detail.setText(message); self.progress.setValue(0)
        if "Open Setup" in message or "not ready" in message:
            self._navigate(3)
        QMessageBox.critical(self, "ZeroReels", message)

    def _open_output(self):
        if self.current_project and self.current_project.video_path:
            QDesktopServices.openUrl(QUrl.fromLocalFile(self.current_project.video_path))

    def _open_project_folder(self):
        if self.current_project and self.current_project.output_dir:
            QDesktopServices.openUrl(QUrl.fromLocalFile(self.current_project.output_dir))

    def _refresh_scenes(self):
        if not hasattr(self, "scene_layout"):
            return
        while self.scene_layout.count() > 1:
            item = self.scene_layout.takeAt(0)
            if item.widget(): item.widget().deleteLater()
        if not self.current_project or not self.current_project.scenes:
            empty = QLabel("Generate a reel first. Your scenes will appear here."); empty.setObjectName("Subtitle")
            self.scene_layout.insertWidget(0, empty); return
        portrait = self.current_project.format == "9:16"
        for scene in self.current_project.scenes:
            card = Card(); row = QHBoxLayout(card); row.setContentsMargins(16, 16, 16, 16); row.setSpacing(16)
            preview = QLabel(); preview.setFixedSize(126 if portrait else 180, 180 if portrait else 102); preview.setAlignment(Qt.AlignCenter)
            preview.setStyleSheet(f"background:{SURFACE_2}; border-radius:10px;")
            if scene.image_path and Path(scene.image_path).exists():
                pix = QPixmap(scene.image_path)
                if not pix.isNull():
                    preview.setPixmap(pix.scaled(preview.size(), Qt.KeepAspectRatioByExpanding, Qt.SmoothTransformation))
            text = QVBoxLayout()
            title = QLabel(f"Scene {scene.index:02d}  •  {scene.duration:.1f}s"); title.setObjectName("Section")
            narration = QLabel(scene.narration); narration.setWordWrap(True)
            prompt = QLabel(scene.image_prompt); prompt.setWordWrap(True); prompt.setObjectName("Subtitle")
            text.addWidget(title); text.addWidget(narration); text.addSpacing(5); text.addWidget(prompt); text.addStretch(1)
            row.addWidget(preview); row.addLayout(text, 1)
            self.scene_layout.insertWidget(self.scene_layout.count() - 1, card)

    def _add_to_queue(self):
        topic = self.topic.toPlainText().strip()
        if topic:
            self.queue_list.addItem(topic); self.status_detail.setText("Added to queue.")

    def _load_next_queue(self):
        if self.queue_list.count() == 0:
            return
        item = self.queue_list.takeItem(0); self.topic.setPlainText(item.text()); self._navigate(0)
