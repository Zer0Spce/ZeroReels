from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QFrame,
    QGridLayout,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QPlainTextEdit,
    QPushButton,
    QScrollArea,
    QSizePolicy,
    QSpinBox,
    QVBoxLayout,
    QWidget,
)

from . import ui


def _combo(items: list[str], current: str) -> QComboBox:
    box = QComboBox()
    box.addItems(items)
    box.setCurrentText(current if current in items else items[0])
    return box


def _enforce_control_heights(container: QWidget) -> None:
    # Never let Qt/DPI scaling collapse interactive controls into 15–20 px slivers.
    for widget in container.findChildren((QComboBox, QSpinBox, QLineEdit, QPushButton)):
        widget.setMinimumHeight(38)
        widget.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
    for widget in container.findChildren(QCheckBox):
        widget.setMinimumHeight(26)
    for widget in container.findChildren(QPlainTextEdit):
        if widget.objectName() != "create_live_log":
            widget.setMinimumHeight(84)


def install() -> None:
    original_sidebar = ui.MainWindow._sidebar
    original_create_page = ui.MainWindow._create_page
    original_options = ui.MainWindow._options
    original_generate = ui.MainWindow._generate
    original_complete = ui.MainWindow._on_complete

    def sidebar(self):
        frame = original_sidebar(self)
        for label in frame.findChildren(QLabel):
            if label.text().startswith("v0."):
                label.setText("v0.7.1 MIX")
                label.setMaximumWidth(112)
                break
        return frame

    def create_page(self):
        page = original_create_page(self)
        root = page.layout()
        if not isinstance(root, QVBoxLayout):
            return page

        main_card = self.topic.parentWidget()
        quality_card = self.continuity_box.parentWidget()
        status_card = self.progress.parentWidget()
        log_card = self.create_live_log.parentWidget()

        grid = quality_card.layout()
        if isinstance(grid, QGridLayout):
            current_mode = getattr(self.settings, "image_source_mode", "AI Generated")
            self.image_source_box = _combo(
                ["AI Generated", "Real Web Images", "Hybrid"],
                current_mode,
            )
            self.image_source_box.setToolTip(
                "AI Generated uses local FLUX only. Real Web Images searches Wikimedia Commons for authentic, license-traceable imagery. Hybrid mixes real imagery with AI-directed scenes."
            )
            self.research_grounding_check = QCheckBox("Research grounding")
            self.research_grounding_check.setChecked(bool(getattr(self.settings, "research_grounding", False)))
            self.research_grounding_check.setToolTip(
                "Opt-in internet feature. Pulls a small Wikipedia context before script writing so factual/history topics stay grounded and less generic."
            )

            source_label = QLabel("Image source"); source_label.setObjectName("Hint")
            research_label = QLabel("Story research"); research_label.setObjectName("Hint")
            grid.addWidget(source_label, 14, 0)
            grid.addWidget(research_label, 14, 1)
            grid.addWidget(self.image_source_box, 15, 0)
            grid.addWidget(self.research_grounding_check, 15, 1)

            note = QLabel(
                "Real/Hybrid mode uses Wikimedia Commons instead of scraping Google Images, so ZeroReels can keep source, credit and license metadata in the project."
            )
            note.setObjectName("Hint")
            note.setWordWrap(True)
            grid.addWidget(note, 16, 0, 1, 2)

            def source_changed(value: str) -> None:
                # Network features stay opt-in in the all-local default, but choosing a web source
                # enables grounding automatically because that mode already requires internet.
                if value in {"Real Web Images", "Hybrid"}:
                    self.research_grounding_check.setChecked(True)

            self.image_source_box.currentTextChanged.connect(source_changed)

        # PERMANENT responsive-layout fix: detach the four functional cards from the old
        # dashboard wrapper, then rebuild the page inside a vertical scroll area. This stops
        # later feature rows from forcing Qt to compress comboboxes/buttons at 100–150% DPI.
        for card in (main_card, quality_card, status_card, log_card):
            card.setParent(page)

        while root.count() > 2:
            item = root.takeAt(2)
            widget = item.widget()
            if widget and widget not in {main_card, quality_card, status_card, log_card}:
                widget.setParent(None)
                widget.deleteLater()

        main_card.setMinimumHeight(350)
        quality_card.setMinimumHeight(455)
        status_card.setMinimumHeight(118)
        log_card.setMinimumHeight(190)
        self.create_live_log.setMinimumHeight(145)
        self.create_live_log.setMaximumHeight(16777215)

        content = QWidget()
        content.setObjectName("CreateResponsiveContent")
        body = QVBoxLayout(content)
        body.setContentsMargins(2, 2, 2, 8)
        body.setSpacing(14)

        top = QWidget()
        top_layout = QHBoxLayout(top)
        top_layout.setContentsMargins(0, 0, 0, 0)
        top_layout.setSpacing(14)
        top_layout.addWidget(main_card, 3, Qt.AlignTop)
        top_layout.addWidget(quality_card, 2, Qt.AlignTop)
        body.addWidget(top)
        body.addWidget(status_card)
        body.addWidget(log_card)
        body.addStretch(1)

        scroll = QScrollArea(page)
        scroll.setObjectName("CreateResponsiveScroll")
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.NoFrame)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        scroll.setVerticalScrollBarPolicy(Qt.ScrollBarAsNeeded)
        scroll.setWidget(content)
        self.create_scroll_area = scroll
        root.addWidget(scroll, 1)

        _enforce_control_heights(content)
        self.topic.setMinimumHeight(92)
        self.topic.setMaximumHeight(110)

        # A little more breathing room at the minimum supported window width.
        if isinstance(main_card.layout(), QGridLayout):
            main_card.layout().setVerticalSpacing(11)
        if isinstance(quality_card.layout(), QGridLayout):
            quality_card.layout().setVerticalSpacing(8)
            quality_card.layout().setColumnStretch(0, 1)
            quality_card.layout().setColumnStretch(1, 1)

        return page

    def options(self):
        opts = original_options(self)
        opts.image_source_mode = self.image_source_box.currentText()
        opts.research_grounding = self.research_grounding_check.isChecked()
        return opts

    def generate(self):
        self.settings.image_source_mode = self.image_source_box.currentText()
        self.settings.research_grounding = self.research_grounding_check.isChecked()
        self.settings.save()
        result = original_generate(self)
        if getattr(self, "worker", None) and self.worker.isRunning() and hasattr(self, "_append_create_log"):
            self._append_create_log(
                f"Reality Mix: {self.image_source_box.currentText()} • research "
                f"{'ON' if self.research_grounding_check.isChecked() else 'OFF'}"
            )
        return result

    def complete(self, project):
        result = original_complete(self, project)
        if hasattr(self, "status_detail"):
            current = self.status_detail.text()
            source = getattr(project, "image_source_mode", "AI Generated")
            suffix = f"visuals: {source}"
            if suffix not in current:
                self.status_detail.setText((current + "  •  " + suffix).strip(" •"))
        return result

    ui.MainWindow._sidebar = sidebar
    ui.MainWindow._create_page = create_page
    ui.MainWindow._options = options
    ui.MainWindow._generate = generate
    ui.MainWindow._on_complete = complete
