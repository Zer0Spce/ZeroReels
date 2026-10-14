from __future__ import annotations

from PySide6.QtWidgets import (
    QHBoxLayout,
    QLabel,
    QMessageBox,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from . import ui


def build_stylesheet() -> str:
    """Clean black/yellow theme without opaque backgrounds behind every label."""
    return f"""
    * {{ font-family: 'Segoe UI'; font-size: 10.25pt; }}
    QMainWindow {{ background: {ui.BG}; color: {ui.TEXT}; }}
    QWidget {{ color: {ui.TEXT}; background: transparent; }}
    QStackedWidget {{ background: {ui.BG}; }}
    QLabel {{ background: transparent; border: 0; }}
    QLabel#Title {{ font-size: 25pt; font-weight: 850; letter-spacing: 0.2px; }}
    QLabel#Subtitle {{ color: {ui.MUTED}; font-size: 9.8pt; }}
    QLabel#Section {{ font-size: 12.5pt; font-weight: 760; }}
    QLabel#Badge {{ background: rgba(246,201,69,0.10); color: {ui.ACCENT}; border: 1px solid rgba(246,201,69,0.34); border-radius: 9px; padding: 3px 8px; font-weight: 800; }}
    QLabel#Hint {{ color: {ui.MUTED}; font-size: 9.3pt; }}

    QFrame#Card {{ background: #101012; border: 1px solid #29292C; border-radius: 14px; }}
    QFrame#Sidebar {{ background: #080809; border-right: 1px solid #202023; }}

    QLineEdit, QPlainTextEdit, QComboBox, QSpinBox, QListWidget {{
        background: #171719; border: 1px solid #303034; border-radius: 9px;
        padding: 8px 10px; selection-background-color: {ui.ACCENT}; selection-color: #080808;
    }}
    QLineEdit:hover, QPlainTextEdit:hover, QComboBox:hover, QSpinBox:hover {{ border-color: #48484C; }}
    QLineEdit:focus, QPlainTextEdit:focus, QComboBox:focus, QSpinBox:focus {{ border-color: {ui.ACCENT}; }}
    QComboBox::drop-down {{ border: 0; width: 26px; }}

    QCheckBox {{ spacing: 8px; color: #E7E7E2; background: transparent; }}
    QCheckBox::indicator {{ width: 17px; height: 17px; border-radius: 5px; border: 1px solid #4A4A4E; background: #151517; }}
    QCheckBox::indicator:hover {{ border-color: {ui.ACCENT}; }}
    QCheckBox::indicator:checked {{ background: {ui.ACCENT}; border-color: {ui.ACCENT}; }}

    QPushButton {{ background: #19191B; border: 1px solid #303034; border-radius: 9px; padding: 8px 13px; font-weight: 680; }}
    QPushButton:hover {{ background: #222225; border-color: #4A4A4E; }}
    QPushButton:pressed {{ background: #111113; padding-top: 9px; padding-bottom: 7px; }}
    QPushButton:disabled {{ color: #66666A; background: #121214; border-color: #202023; }}
    QPushButton#Primary {{ background: {ui.ACCENT}; color: #090909; border-color: {ui.ACCENT}; font-weight: 850; }}
    QPushButton#Primary:hover {{ background: {ui.ACCENT_HOVER}; border-color: #FFE88A; }}
    QPushButton#SecondaryAccent {{ color: {ui.ACCENT}; border-color: rgba(246,201,69,0.46); }}
    QPushButton#SecondaryAccent:hover {{ background: rgba(246,201,69,0.08); border-color: {ui.ACCENT}; }}
    QPushButton#Nav {{ text-align: left; border: 0; background: transparent; color: {ui.MUTED}; padding: 10px 12px; }}
    QPushButton#Nav:hover {{ background: rgba(255,255,255,0.035); color: {ui.TEXT}; }}
    QPushButton#Nav:checked {{ background: rgba(246,201,69,0.10); color: {ui.ACCENT}; border-left: 2px solid {ui.ACCENT}; }}

    QProgressBar {{ background: #19191B; border: 1px solid #29292D; border-radius: 5px; height: 9px; text-align: center; color: transparent; }}
    QProgressBar::chunk {{ background: {ui.ACCENT}; border-radius: 4px; }}
    QScrollArea {{ border: 0; background: transparent; }}
    QScrollBar:vertical {{ background: transparent; width: 9px; margin: 2px; }}
    QScrollBar::handle:vertical {{ background: #3A3A3E; border-radius: 4px; min-height: 30px; }}
    QScrollBar::handle:vertical:hover {{ background: #555559; }}
    QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical {{ height: 0; }}
    """


def _remove_spacers(layout) -> None:
    if layout is None:
        return
    for index in range(layout.count() - 1, -1, -1):
        item = layout.itemAt(index)
        if item and item.spacerItem() is not None:
            layout.takeAt(index)


def _reparent_for_layout(widget, new_parent: QWidget) -> None:
    parent = widget.parentWidget()
    if parent and parent.layout():
        parent.layout().removeWidget(widget)
    widget.setParent(new_parent)


def install() -> None:
    ui.build_stylesheet = build_stylesheet

    original_sidebar = ui.MainWindow._sidebar
    original_create_page = ui.MainWindow._create_page
    original_setup_page = ui.MainWindow._setup_page
    original_generate = ui.MainWindow._generate

    def sidebar(self):
        frame = original_sidebar(self)
        for label in frame.findChildren(QLabel):
            if label.text() == "v0.5 QUALITY":
                label.setText("v0.5.1")
                label.setMaximumWidth(82)
        return frame

    def create_page(self):
        page = original_create_page(self)
        root = page.layout()
        root.setSpacing(13)
        root.setContentsMargins(30, 24, 30, 24)

        main_card = self.topic.parentWidget()
        quality_card = self.continuity_box.parentWidget()
        status_card = self.progress.parentWidget()
        log_card = self.create_live_log.parentWidget()

        # Pull the useful cards out of the older v0.5 dashboard containers.
        for card in (main_card, quality_card, status_card, log_card):
            _reparent_for_layout(card, page)

        # Keep the title + subtitle and remove the old dashboard wrappers/stretch.
        while root.count() > 2:
            item = root.takeAt(2)
            widget = item.widget() if item else None
            if widget and widget not in (main_card, quality_card, status_card, log_card):
                widget.deleteLater()

        self.topic.setMinimumHeight(68)
        self.topic.setMaximumHeight(78)
        main_card.setMinimumHeight(300)

        mid = QWidget(page)
        mid_layout = QHBoxLayout(mid)
        mid_layout.setContentsMargins(0, 0, 0, 0)
        mid_layout.setSpacing(13)
        quality_card.setMinimumHeight(150)
        status_card.setMinimumHeight(150)
        mid_layout.addWidget(quality_card, 3)
        mid_layout.addWidget(status_card, 2)

        self.create_live_log.setMinimumHeight(105)
        self.create_live_log.setMaximumHeight(128)

        root.addWidget(main_card)
        root.addWidget(mid)
        root.addWidget(log_card)
        root.addStretch(1)

        # Reconnect explicitly after every v0.5 layout transformation. This prevents
        # a stale bound slot from making the primary action look clickable but do nothing.
        try:
            self.generate.clicked.disconnect()
        except (TypeError, RuntimeError):
            pass
        self.generate.clicked.connect(lambda checked=False: self._generate())
        self.generate.setToolTip("Start the local ZeroReels generation pipeline")
        return page

    def setup_page(self):
        page = original_setup_page(self)
        root = page.layout()
        root.setSpacing(13)
        root.setContentsMargins(30, 24, 30, 24)

        # _setup_card historically inserted a stretch before action buttons. Remove it
        # and compact the multi-button cards so controls never get vertically clipped.
        cards: dict[str, QWidget] = {}
        for badge in page.findChildren(QLabel):
            if badge.objectName() == "Badge" and badge.text() in {"1", "2", "3", "4"}:
                card = badge.parentWidget()
                if card:
                    cards[badge.text()] = card

        for card in cards.values():
            body = card.layout()
            _remove_spacers(body)
            if body:
                body.setSpacing(8)
                body.setContentsMargins(16, 15, 16, 15)

        def buttons(card):
            return {button.text(): button for button in card.findChildren(QPushButton)} if card else {}

        # Script AI: two actions on one clean row.
        card1 = cards.get("1")
        if card1 and card1.layout():
            b = buttons(card1)
            install_btn = b.get("Install Ollama")
            model_btn = b.get("Download Script Model")
            if install_btn and model_btn:
                card1.layout().removeWidget(install_btn)
                card1.layout().removeWidget(model_btn)
                row = QHBoxLayout()
                row.setSpacing(8)
                row.addWidget(install_btn)
                row.addWidget(model_btn)
                card1.layout().addLayout(row)

        # Image AI: installation/folder side-by-side, model download full width below.
        card2 = cards.get("2")
        if card2 and card2.layout():
            b = buttons(card2)
            install_btn = b.get("Install ComfyUI Desktop")
            detect_btn = b.get("Detect / Select Data Folder")
            flux_btn = b.get("Download FLUX.2 Model Pack")
            if install_btn and detect_btn and flux_btn:
                for button in (install_btn, detect_btn, flux_btn):
                    card2.layout().removeWidget(button)
                row = QHBoxLayout()
                row.setSpacing(8)
                row.addWidget(install_btn)
                row.addWidget(detect_btn)
                card2.layout().addLayout(row)
                card2.layout().addWidget(flux_btn)

        if hasattr(self, "setup_log"):
            self.setup_log.setMinimumHeight(120)
            self.setup_log.setMaximumHeight(180)
            self.setup_log.setStyleSheet(
                "QPlainTextEdit { background:#09090A; color:#D7D7D2; border:1px solid #29292D; "
                "border-radius:9px; padding:10px; font-family:'Cascadia Mono','Consolas'; font-size:9.2pt; }"
            )
        return page

    def generate(self):
        # UI-side errors previously disappeared into Qt's signal dispatch. Surface them
        # in both the Create log and a dialog so Generate can never fail silently.
        try:
            return original_generate(self)
        except Exception as exc:  # pragma: no cover - exercised through UI integration test
            message = str(exc) or exc.__class__.__name__
            if hasattr(self, "_append_create_log"):
                self._append_create_log(f"ERROR  {message}")
            if hasattr(self, "status_text"):
                self.status_text.setText("Generation stopped")
            if hasattr(self, "status_detail"):
                self.status_detail.setText(message)
            if hasattr(self, "generate"):
                self.generate.setEnabled(True)
            if hasattr(self, "queue_add"):
                self.queue_add.setEnabled(True)
            QMessageBox.critical(self, "ZeroReels", message)
            return None

    ui.MainWindow._sidebar = sidebar
    ui.MainWindow._create_page = create_page
    ui.MainWindow._setup_page = setup_page
    ui.MainWindow._generate = generate
