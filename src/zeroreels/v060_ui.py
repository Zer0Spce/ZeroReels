from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import Qt
from PySide6.QtGui import QPixmap
from PySide6.QtWidgets import QCheckBox, QComboBox, QGridLayout, QHBoxLayout, QLabel, QVBoxLayout

from . import ui


def _combo(items: list[str], current: str) -> QComboBox:
    box = QComboBox()
    box.addItems(items)
    box.setCurrentText(current)
    return box


def install() -> None:
    original_sidebar = ui.MainWindow._sidebar
    original_create_page = ui.MainWindow._create_page
    original_options = ui.MainWindow._options
    original_generate = ui.MainWindow._generate
    original_complete = ui.MainWindow._on_complete

    def sidebar(self):
        frame = original_sidebar(self)
        for label in frame.findChildren(QLabel):
            if label.text() in {"v0.5.3", "v0.5.2", "v0.5.1", "v0.5 QUALITY"}:
                label.setText("v0.6 PRO")
                label.setMaximumWidth(92)
        return frame

    def create_page(self):
        page = original_create_page(self)
        quality_card = self.continuity_box.parentWidget()
        grid = quality_card.layout()
        if isinstance(grid, QGridLayout):
            continuity_items = [self.continuity_box.itemText(i) for i in range(self.continuity_box.count())]
            if "Hero Character Lock" not in continuity_items:
                self.continuity_box.insertItem(1, "Hero Character Lock")
            self.continuity_box.setToolTip(
                "Hero Character Lock is ZeroReels' strongest prompt/seed identity lock with the current local FLUX stack. "
                "It improves recurring-person consistency while still generating a fresh shot every scene."
            )

            self.caption_style_box = _combo(
                ["TikTok Pop", "Clean Lower Third", "Documentary"],
                "TikTok Pop",
            )
            self.caption_style_box.setToolTip(
                "TikTok Pop uses short phrase captions, a subtle pop-in and one yellow keyword for fast readability."
            )
            self.soundtrack_box = _combo(
                ["Auto Ambience", "Local Music Folder", "Off"],
                "Auto Ambience",
            )
            self.soundtrack_box.setToolTip(
                "Auto Ambience is generated locally. Local Music Folder uses your own audio files from Settings and ducks them under narration."
            )
            self.sfx_check = QCheckBox("Subtle transition SFX")
            self.sfx_check.setChecked(True)
            self.quality_guard_check = QCheckBox("Auto-regenerate weak scenes")
            self.quality_guard_check.setChecked(True)
            self.quality_guard_check.setToolTip(
                "Checks for invalid/flat images, strong split-panel seams and near-duplicate scenes, then retries up to two times."
            )

            cap_label = QLabel("Caption style"); cap_label.setObjectName("Hint")
            sound_label = QLabel("Soundtrack"); sound_label.setObjectName("Hint")
            grid.addWidget(cap_label, 6, 0)
            grid.addWidget(sound_label, 6, 1)
            grid.addWidget(self.caption_style_box, 7, 0)
            grid.addWidget(self.soundtrack_box, 7, 1)
            grid.addWidget(self.quality_guard_check, 8, 0)
            grid.addWidget(self.sfx_check, 8, 1)
            grid.setRowStretch(9, 0)
        return page

    def options(self):
        opts = original_options(self)
        opts.caption_style = self.caption_style_box.currentText()
        opts.soundtrack_mode = self.soundtrack_box.currentText()
        opts.music = opts.soundtrack_mode != "Off"
        opts.sfx = self.sfx_check.isChecked()
        opts.quality_guard = self.quality_guard_check.isChecked()
        opts.quality_retries = 2
        return opts

    def generate(self):
        result = original_generate(self)
        if getattr(self, "worker", None) and self.worker.isRunning() and hasattr(self, "_append_create_log"):
            self._append_create_log(
                f"Professional polish: {self.caption_style_box.currentText()} captions • "
                f"{self.soundtrack_box.currentText()} • "
                f"quality guard {'ON' if self.quality_guard_check.isChecked() else 'OFF'} • "
                f"SFX {'ON' if self.sfx_check.isChecked() else 'OFF'}"
            )
        return result

    def complete(self, project):
        result = original_complete(self, project)
        parts = [f"{project.actual_seconds:.1f}s actual / {project.target_seconds}s target"]
        if project.quality_summary:
            parts.append(project.quality_summary)
        if project.soundtrack_used:
            parts.append(f"audio: {project.soundtrack_used}")
        self.status_detail.setText("  •  ".join(parts))
        return result

    def refresh_scenes(self):
        if not hasattr(self, "scene_layout"):
            return
        while self.scene_layout.count() > 1:
            item = self.scene_layout.takeAt(0)
            if item.widget():
                item.widget().deleteLater()
        if not self.current_project or not self.current_project.scenes:
            empty = QLabel("Generate a reel first. Your scenes will appear here.")
            empty.setObjectName("Subtitle")
            self.scene_layout.insertWidget(0, empty)
            return

        portrait = self.current_project.format == "9:16"
        for scene in self.current_project.scenes:
            card = ui.Card()
            row = QHBoxLayout(card)
            row.setContentsMargins(16, 16, 16, 16)
            row.setSpacing(16)
            preview = QLabel()
            preview.setFixedSize(126 if portrait else 180, 180 if portrait else 102)
            preview.setAlignment(Qt.AlignCenter)
            preview.setStyleSheet(f"background:{ui.SURFACE_2}; border-radius:10px;")
            if scene.image_path and Path(scene.image_path).exists():
                pix = QPixmap(scene.image_path)
                if not pix.isNull():
                    preview.setPixmap(pix.scaled(preview.size(), Qt.KeepAspectRatioByExpanding, Qt.SmoothTransformation))

            text = QVBoxLayout()
            quality = f"Q{scene.quality_score}" if scene.quality_score else "Q—"
            retries = f" • retry {scene.retry_count}" if scene.retry_count else ""
            title = QLabel(
                f"Scene {scene.index:02d}  •  {scene.duration:.1f}s  •  {scene.shot_role or 'Shot'}  •  {quality}{retries}"
            )
            title.setObjectName("Section")
            narration = QLabel(scene.narration)
            narration.setWordWrap(True)
            meta_parts = []
            if scene.motion_style:
                meta_parts.append(f"Motion: {scene.motion_style}")
            if scene.transition_to_next:
                meta_parts.append(f"Next: {scene.transition_to_next}")
            if scene.quality_notes:
                meta_parts.append("Quality: " + ", ".join(scene.quality_notes[:2]))
            meta = QLabel("  •  ".join(meta_parts))
            meta.setWordWrap(True)
            meta.setObjectName("Hint")
            prompt = QLabel(scene.image_prompt)
            prompt.setWordWrap(True)
            prompt.setObjectName("Subtitle")
            text.addWidget(title)
            text.addWidget(narration)
            if meta_parts:
                text.addWidget(meta)
            text.addSpacing(4)
            text.addWidget(prompt)
            text.addStretch(1)
            row.addWidget(preview)
            row.addLayout(text, 1)
            self.scene_layout.insertWidget(self.scene_layout.count() - 1, card)

    ui.MainWindow._sidebar = sidebar
    ui.MainWindow._create_page = create_page
    ui.MainWindow._options = options
    ui.MainWindow._generate = generate
    ui.MainWindow._on_complete = complete
    ui.MainWindow._refresh_scenes = refresh_scenes
