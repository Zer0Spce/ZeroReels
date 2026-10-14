from __future__ import annotations

from datetime import datetime

from PySide6.QtCore import QThread, Signal
from PySide6.QtWidgets import (
    QGridLayout,
    QHBoxLayout,
    QLabel,
    QMessageBox,
    QPlainTextEdit,
    QProgressBar,
    QVBoxLayout,
    QWidget,
)

from . import setup_tools
from . import ui


class LiveSetupThread(QThread):
    progress_changed = Signal(int, str)
    log_changed = Signal(str)
    completed = Signal(str)
    failed = Signal(str)

    def __init__(self, label: str, action):
        super().__init__()
        self.label = label
        self.action = action

    def run(self):
        self.log_changed.emit(f"Starting: {self.label}")
        try:
            self.action(self.progress_changed.emit, self.log_changed.emit)
            self.log_changed.emit(f"Finished: {self.label}")
            self.completed.emit(self.label)
        except Exception as exc:
            message = str(exc) or exc.__class__.__name__
            self.log_changed.emit(f"ERROR: {message}")
            self.failed.emit(message)


def _append_setup_log(self, text: str) -> None:
    if not text or not hasattr(self, "setup_log"):
        return
    stamp = datetime.now().strftime("%H:%M:%S")
    normalized = str(text).replace("\r", "\n")
    for raw in normalized.splitlines():
        line = raw.strip()
        if line:
            self.setup_log.appendPlainText(f"[{stamp}] {line}")
    bar = self.setup_log.verticalScrollBar()
    bar.setValue(bar.maximum())


def _on_setup_progress(self, value: int, text: str) -> None:
    if self.setup_progress.maximum() == 0:
        self.setup_progress.setRange(0, 100)
    self.setup_progress.setValue(max(0, min(100, int(value))))
    self.setup_status.setText(text)
    self._append_setup_log(text)


def _run_setup(self, label: str, action) -> None:
    if self.setup_worker and self.setup_worker.isRunning():
        self._append_setup_log("A setup task is already running. Wait for it to finish.")
        return
    self.setup_progress.setRange(0, 0)
    self.setup_status.setText(f"Working: {label}")
    self._append_setup_log("────────────────────────────────────────────────────")
    self._append_setup_log(label)
    self.setup_worker = LiveSetupThread(label, action)
    self.setup_worker.progress_changed.connect(self._on_setup_progress)
    self.setup_worker.log_changed.connect(self._append_setup_log)
    self.setup_worker.completed.connect(self._setup_complete)
    self.setup_worker.failed.connect(self._setup_failed)
    self.setup_worker.start()


def _setup_complete(self, label: str) -> None:
    self.setup_progress.setRange(0, 100)
    self.setup_progress.setValue(100)
    self.setup_status.setText(label)
    self._append_setup_log(f"✓ {label}")
    self._refresh_setup_summary()
    self._refresh_diagnostics()


def _setup_failed(self, message: str) -> None:
    self.setup_progress.setRange(0, 100)
    self.setup_progress.setValue(0)
    self.setup_status.setText("Setup task failed — see Live Log")
    self._append_setup_log(f"✕ {message}")
    QMessageBox.critical(self, "ZeroReels Setup", message)


def _setup_page(self) -> QWidget:
    page, layout = self._page(
        "First-Time Setup",
        "Everything stays local and free. Install the engines once, then ZeroReels can generate videos without paid APIs.",
    )

    summary = ui.Card()
    sum_box = QVBoxLayout(summary)
    sum_box.setContentsMargins(20, 18, 20, 18)
    row = QHBoxLayout()
    title = QLabel("System readiness")
    title.setObjectName("Section")
    row.addWidget(title)
    row.addStretch(1)
    refresh = ui.SoftButton("Refresh")
    refresh.clicked.connect(self._refresh_setup_summary)
    row.addWidget(refresh)
    sum_box.addLayout(row)
    self.gpu_label = QLabel(setup_tools.gpu_summary())
    self.gpu_label.setObjectName("Subtitle")
    sum_box.addWidget(self.gpu_label)
    self.setup_summary = QLabel("Checking local components...")
    self.setup_summary.setWordWrap(True)
    sum_box.addWidget(self.setup_summary)
    layout.addWidget(summary)

    grid_wrap = QWidget()
    grid = QGridLayout(grid_wrap)
    grid.setContentsMargins(0, 0, 0, 0)
    grid.setSpacing(14)

    card1, body1 = self._setup_card("1", "Script AI", "Ollama + Qwen run the script and scene planner entirely on your PC.")
    install_o = ui.SoftButton("Install Ollama")
    install_o.clicked.connect(lambda: self._run_setup("Ollama installed", lambda progress, log: setup_tools.install_ollama(log=log)))
    pull = ui.SoftButton("Download Script Model")
    pull.setObjectName("Primary")
    pull.clicked.connect(lambda: self._run_setup("Script model ready", lambda progress, log: setup_tools.pull_ollama_model(self.settings.ollama_model, progress=progress, log=log)))
    body1.addWidget(install_o)
    body1.addWidget(pull)
    grid.addWidget(card1, 0, 0)

    card2, body2 = self._setup_card("2", "Image AI", "ComfyUI Desktop + FLUX.2 Klein 4B generate every scene locally. Model download is large (~15 GB+).")
    install_c = ui.SoftButton("Install ComfyUI Desktop")
    install_c.clicked.connect(lambda: self._run_setup("ComfyUI installed", lambda progress, log: setup_tools.install_comfyui(log=log)))
    detect = ui.SoftButton("Detect / Select Data Folder")
    detect.clicked.connect(self._select_comfy_root)
    flux = ui.SoftButton("Download FLUX.2 Model Pack")
    flux.setObjectName("Primary")
    flux.clicked.connect(self._download_flux)
    body2.addWidget(install_c)
    body2.addWidget(detect)
    body2.addWidget(flux)
    grid.addWidget(card2, 0, 1)

    card3, body3 = self._setup_card("3", "Voice", "Kokoro generates natural narration locally. ZeroReels includes the engine; download the compact local model and voice pack once.")
    voice = ui.SoftButton("Download Kokoro Voice Files")
    voice.setObjectName("Primary")
    voice.clicked.connect(lambda: self._run_setup("Voice ready", lambda progress, log: setup_tools.download_kokoro_models(self.settings, progress=progress, log=log)))
    body3.addWidget(voice)
    grid.addWidget(card3, 1, 0)

    card4, body4 = self._setup_card("4", "Finish", "Open Ollama and ComfyUI, refresh diagnostics, then generate from the Create page.")
    diag = ui.SoftButton("Open Diagnostics")
    diag.setObjectName("Primary")
    diag.clicked.connect(lambda: self._navigate(5))
    body4.addWidget(diag)
    grid.addWidget(card4, 1, 1)

    grid.setColumnStretch(0, 1)
    grid.setColumnStretch(1, 1)
    layout.addWidget(grid_wrap)

    log_card = ui.Card()
    log_box = QVBoxLayout(log_card)
    log_box.setContentsMargins(20, 16, 20, 16)
    log_box.setSpacing(9)

    header = QHBoxLayout()
    log_title = QLabel("Live Log")
    log_title.setObjectName("Section")
    hint = QLabel("Installer and download output appears here in real time")
    hint.setObjectName("Subtitle")
    clear = ui.SoftButton("Clear")
    header.addWidget(log_title)
    header.addWidget(hint)
    header.addStretch(1)
    header.addWidget(clear)
    log_box.addLayout(header)

    self.setup_log = QPlainTextEdit()
    self.setup_log.setReadOnly(True)
    self.setup_log.setMaximumBlockCount(2500)
    self.setup_log.setMinimumHeight(150)
    self.setup_log.setPlaceholderText("Start a setup task to see live output...")
    self.setup_log.setStyleSheet("QPlainTextEdit { background:#070B10; color:#C8D3DE; border:1px solid #24303D; border-radius:10px; padding:10px; font-family:'Cascadia Mono','Consolas'; font-size:9.5pt; }")
    clear.clicked.connect(self.setup_log.clear)
    log_box.addWidget(self.setup_log)

    self.setup_progress = QProgressBar()
    self.setup_progress.setRange(0, 100)
    self.setup_progress.setValue(0)
    self.setup_status = QLabel("Ready. Select a setup task above.")
    self.setup_status.setObjectName("Subtitle")
    log_box.addWidget(self.setup_progress)
    log_box.addWidget(self.setup_status)
    layout.addWidget(log_card)

    self._append_setup_log("ZeroReels Setup Live Log ready.")
    layout.addStretch(1)
    return page


def _download_flux(self) -> None:
    root = self.settings.comfy_root or (str(ui.detect_comfy_root()) if ui.detect_comfy_root() else "")
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
        self._run_setup("FLUX.2 model pack ready", lambda progress, log: setup_tools.download_flux_models(self.settings, progress=progress, log=log))


def install() -> None:
    ui.SetupThread = LiveSetupThread
    ui.MainWindow._append_setup_log = _append_setup_log
    ui.MainWindow._on_setup_progress = _on_setup_progress
    ui.MainWindow._run_setup = _run_setup
    ui.MainWindow._setup_complete = _setup_complete
    ui.MainWindow._setup_failed = _setup_failed
    ui.MainWindow._setup_page = _setup_page
    ui.MainWindow._download_flux = _download_flux
