from __future__ import annotations

from PySide6.QtWidgets import QGridLayout, QHBoxLayout, QLabel, QVBoxLayout, QWidget

from . import ui


def install() -> None:
    original_create_page = ui.MainWindow._create_page

    def create_page(self):
        page = original_create_page(self)
        root = page.layout()

        main_card = self.topic.parentWidget()
        quality_card = self.continuity_box.parentWidget()
        status_card = self.progress.parentWidget()
        log_card = self.create_live_log.parentWidget()

        for widget in (main_card, quality_card, status_card, log_card):
            root.removeWidget(widget)

        # Remove the old trailing stretch from the original vertically stacked page.
        for index in range(root.count() - 1, -1, -1):
            item = root.itemAt(index)
            if item and item.spacerItem() is not None:
                root.takeAt(index)

        # The quality card is narrower in the right rail, so use a clean 2x2 control grid.
        grid = quality_card.layout()
        if isinstance(grid, QGridLayout):
            for label in quality_card.findChildren(QLabel):
                if label.text() in {"Visual continuity", "Caption position", "Caption size", "Transition style"}:
                    label.hide()

            labels = [
                ("Visual continuity", self.continuity_box, 2, 0),
                ("Caption position", self.caption_position_box, 2, 1),
                ("Caption size", self.caption_size_box, 4, 0),
                ("Transition style", self.transition_style_box, 4, 1),
            ]
            for text, control, row, col in labels:
                label = QLabel(text)
                label.setObjectName("Hint")
                grid.addWidget(label, row, col)
                grid.addWidget(control, row + 1, col)
            grid.setColumnStretch(0, 1)
            grid.setColumnStretch(1, 1)

        dashboard = QWidget()
        dash = QHBoxLayout(dashboard)
        dash.setContentsMargins(0, 0, 0, 0)
        dash.setSpacing(16)

        right = QWidget()
        right_box = QVBoxLayout(right)
        right_box.setContentsMargins(0, 0, 0, 0)
        right_box.setSpacing(14)
        right_box.addWidget(quality_card)
        right_box.addWidget(status_card)
        right_box.addStretch(1)

        dash.addWidget(main_card, 3)
        dash.addWidget(right, 2)

        self.create_live_log.setMinimumHeight(105)
        self.create_live_log.setMaximumHeight(140)
        root.addWidget(dashboard, 1)
        root.addWidget(log_card)
        return page

    ui.MainWindow._create_page = create_page
