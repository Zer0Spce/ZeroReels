from __future__ import annotations

from datetime import datetime

from PySide6.QtCore import QEasingCurve
from PySide6.QtGui import QColor
from PySide6.QtWidgets import QFrame, QHBoxLayout, QLabel, QPlainTextEdit, QVBoxLayout

from . import ui


def build_stylesheet() -> str:
    return f"""
    * {{ font-family: 'Segoe UI'; font-size: 10.5pt; }}
    QMainWindow, QWidget {{ background: {ui.BG}; color: {ui.TEXT}; }}
    QLabel#Title {{ font-size: 25pt; font-weight: 850; letter-spacing: 0.2px; }}
    QLabel#Subtitle {{ color: {ui.MUTED}; font-size: 10pt; }}
    QLabel#Section {{ font-size: 13pt; font-weight: 750; }}
    QLabel#Badge {{ background: rgba(246,201,69,0.10); color: {ui.ACCENT}; border: 1px solid rgba(246,201,69,0.34); border-radius: 9px; padding: 3px 8px; font-weight: 800; }}
    QLabel#Hint {{ color: {ui.MUTED}; font-size: 9.5pt; }}
    QFrame#Card {{ background: {ui.SURFACE}; border: 1px solid {ui.BORDER}; border-radius: 15px; }}
    QFrame#Sidebar {{ background: {ui.SIDEBAR}; border-right: 1px solid #1E1E1F; }}
    QLineEdit, QPlainTextEdit, QComboBox, QSpinBox, QListWidget {{
        background: {ui.SURFACE_2}; border: 1px solid {ui.BORDER}; border-radius: 10px;
        padding: 8px 10px; selection-background-color: {ui.ACCENT}; selection-color: #080808;
    }}
    QLineEdit:hover, QPlainTextEdit:hover, QComboBox:hover, QSpinBox:hover {{ border-color: #3A3A3C; }}
    QLineEdit:focus, QPlainTextEdit:focus, QComboBox:focus, QSpinBox:focus {{ border: 1px solid {ui.ACCENT}; }}
    QComboBox::drop-down {{ border: 0; width: 26px; }}
    QCheckBox {{ spacing: 8px; color: #E7E7E1; }}
    QCheckBox::indicator {{ width: 18px; height: 18px; border-radius: 5px; border: 1px solid #454548; background: #151516; }}
    QCheckBox::indicator:hover {{ border-color: {ui.ACCENT}; }}
    QCheckBox::indicator:checked {{ background: {ui.ACCENT}; border: 1px solid {ui.ACCENT}; }}
    QPushButton {{ background: #171718; border: 1px solid #2A2A2C; border-radius: 10px; padding: 9px 14px; font-weight: 680; }}
    QPushButton:hover {{ background: #202021; border-color: #444446; }}
    QPushButton:pressed {{ background: #101011; padding-top: 10px; padding-bottom: 8px; }}
    QPushButton:disabled {{ color: #5E5E60; background: #111112; border-color: #1B1B1C; }}
    QPushButton#Primary {{ background: {ui.ACCENT}; color: #090909; border: 1px solid {ui.ACCENT}; font-weight: 850; }}
    QPushButton#Primary:hover {{ background: {ui.ACCENT_HOVER}; border-color: #FFE78A; }}
    QPushButton#SecondaryAccent {{ color: {ui.ACCENT}; border-color: rgba(246,201,69,0.46); }}
    QPushButton#SecondaryAccent:hover {{ background: rgba(246,201,69,0.08); border-color: {ui.ACCENT}; }}
    QPushButton#Nav {{ text-align: left; border: 0; background: transparent; color: {ui.MUTED}; padding: 10px 12px; }}
    QPushButton#Nav:hover {{ background: rgba(255,255,255,0.035); color: {ui.TEXT}; }}
    QPushButton#Nav:checked {{ background: rgba(246,201,69,0.10); color: {ui.ACCENT}; border-left: 2px solid {ui.ACCENT}; }}
    QProgressBar {{ background: #181819; border: 1px solid #252527; border-radius: 5px; height: 10px; text-align: center; color: transparent; }}
    QProgressBar::chunk {{ background: {ui.ACCENT}; border-radius: 4px; }}
    QScrollArea {{ border: 0; }}
    QScrollBar:vertical {{ background: transparent; width: 9px; margin: 2px; }}
    QScrollBar::handle:vertical {{ background: #39393C; border-radius: 4px; min-height: 30px; }}
    QScrollBar::handle:vertical:hover {{ background: #515154; }}
    QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical {{ height: 0; }}
    """


def _soft_enter(self, event):
    if self.isEnabled():
        self.shadow.setColor(QColor(246, 201, 69, 72))
        self.anim.stop()
        self.anim.setDuration(150)
        self.anim.setEasingCurve(QEasingCurve.OutCubic)
        self.anim.setStartValue(self.shadow.blurRadius())
        self.anim.setEndValue(24)
        self.anim.start()
    super(ui.SoftButton, self).enterEvent(event)


def _soft_leave(self, event):
    self.shadow.setColor(QColor(0, 0, 0, 110))
    self.anim.stop()
    self.anim.setDuration(150)
    self.anim.setStartValue(self.shadow.blurRadius())
    self.anim.setEndValue(12)
    self.anim.start()
    super(ui.SoftButton, self).leaveEvent(event)


def _append_create_log(self, text: str) -> None:
    if not hasattr(self, "create_live_log"):
        return
    stamp = datetime.now().strftime("%H:%M:%S")
    self.create_live_log.appendPlainText(f"[{stamp}] {text}")
    bar = self.create_live_log.verticalScrollBar()
    bar.setValue(bar.maximum())


def _clear_create_log(self) -> None:
    if hasattr(self, "create_live_log"):
        self.create_live_log.clear()
        self._append_create_log("ZeroReels Create Live Log ready.")


def install() -> None:
    ui.ACCENT = "#F6C945"
    ui.ACCENT_HOVER = "#FFD75E"
    ui.BG = "#050506"
    ui.SIDEBAR = "#080809"
    ui.SURFACE = "#0E0E10"
    ui.SURFACE_2 = "#161618"
    ui.TEXT = "#F6F6F1"
    ui.MUTED = "#949497"
    ui.BORDER = "#29292C"
    ui.DANGER = "#FF6B6B"
    ui.WARNING = "#F6C945"
    ui.build_stylesheet = build_stylesheet
    ui.SoftButton.enterEvent = _soft_enter
    ui.SoftButton.leaveEvent = _soft_leave
    ui.MainWindow._append_create_log = _append_create_log
    ui.MainWindow._clear_create_log = _clear_create_log

    original_sidebar = ui.MainWindow._sidebar
    original_create_page = ui.MainWindow._create_page
    original_generate = ui.MainWindow._generate
    original_progress = ui.MainWindow._on_progress
    original_complete = ui.MainWindow._on_complete
    original_failed = ui.MainWindow._on_failed

    def sidebar(self):
        frame = original_sidebar(self)
        for label in frame.findChildren(QLabel):
            if label.text() == "v0.4 REAL":
                label.setText("v0.5 QUALITY")
                label.setMaximumWidth(108)
        return frame

    def create_page(self):
        page = original_create_page(self)
        layout = page.layout()
        card = ui.Card()
        box = QVBoxLayout(card)
        box.setContentsMargins(18, 16, 18, 16)
        box.setSpacing(9)
        top = QHBoxLayout()
        title = QLabel("Live Generation Log")
        title.setObjectName("Section")
        hint = QLabel("Real-time pipeline activity")
        hint.setObjectName("Hint")
        clear = ui.SoftButton("Clear")
        clear.clicked.connect(self._clear_create_log)
        top.addWidget(title)
        top.addSpacing(8)
        top.addWidget(hint)
        top.addStretch(1)
        top.addWidget(clear)
        box.addLayout(top)
        self.create_live_log = QPlainTextEdit()
        self.create_live_log.setReadOnly(True)
        self.create_live_log.setMaximumBlockCount(500)
        self.create_live_log.setMinimumHeight(125)
        self.create_live_log.setMaximumHeight(170)
        self.create_live_log.setStyleSheet(
            "QPlainTextEdit { font-family: 'Cascadia Mono','Consolas'; font-size: 9.2pt; "
            "background:#09090A; border:1px solid #252527; color:#D7D7D2; padding:10px; }"
        )
        box.addWidget(self.create_live_log)
        layout.insertWidget(max(0, layout.count() - 1), card)
        self._clear_create_log()
        return page

    def generate(self):
        if hasattr(self, "create_live_log"):
            self.create_live_log.clear()
            self._append_create_log("Starting a new ZeroReels generation.")
            self._append_create_log(
                f"Format {self.format_box.currentText()} • {self.seconds.value()} sec target • "
                f"{self.scene_count.value()} scenes • {self.style_box.currentText()}"
            )
            self._append_create_log(f"Narrator: {self.voice_box.currentText()}")
        return original_generate(self)

    def progress(self, value: int, text: str):
        last = getattr(self, "_last_create_log_stage", None)
        # Image and voice scene updates are useful individually; repeated status text is not.
        if text != last:
            self._append_create_log(f"{value:>3}%  {text}")
            self._last_create_log_stage = text
        return original_progress(self, value, text)

    def complete(self, project):
        result = original_complete(self, project)
        self._append_create_log("100%  Video ready.")
        self._append_create_log(f"Output: {project.video_path}")
        if project.captions_path:
            self._append_create_log("Captions: burned into video" if project.captions_burned else f"Captions: {project.captions_path}")
        self._append_create_log("Generation finished successfully.")
        return result

    def failed(self, message: str):
        self._append_create_log("ERROR  Generation stopped.")
        for line in str(message).splitlines():
            if line.strip():
                self._append_create_log(line.strip())
        return original_failed(self, message)

    ui.MainWindow._sidebar = sidebar
    ui.MainWindow._create_page = create_page
    ui.MainWindow._generate = generate
    ui.MainWindow._on_progress = progress
    ui.MainWindow._on_complete = complete
    ui.MainWindow._on_failed = failed
