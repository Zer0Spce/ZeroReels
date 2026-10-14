from __future__ import annotations

from pathlib import Path
import os
import shutil

from PySide6.QtWidgets import QFileDialog, QGridLayout, QMessageBox

from . import ui
from .config import detect_comfy_root, normalize_comfy_base


MODEL_FIELDS: dict[str, tuple[str, str]] = {
    "comfy_unet": ("FLUX diffusion model", "diffusion_models"),
    "comfy_clip": ("FLUX text encoder", "text_encoders"),
    "comfy_vae": ("FLUX VAE", "vae"),
}


def _same_path(a: Path, b: Path) -> bool:
    aa = str(a.resolve(strict=False))
    bb = str(b.resolve(strict=False))
    return aa.lower() == bb.lower() if os.name == "nt" else aa == bb


def _append_log(window, text: str) -> None:
    if hasattr(window, "_append_setup_log"):
        try:
            window._append_setup_log(text)
        except Exception:
            pass


def _browse_comfy_model_file(self, key: str) -> None:
    if key not in MODEL_FIELDS:
        return

    label, subfolder = MODEL_FIELDS[key]
    detected = detect_comfy_root()
    root = detected or (normalize_comfy_base(self.settings.comfy_root) if self.settings.comfy_root else None)
    if not root:
        QMessageBox.warning(
            self,
            "ZeroReels",
            "ZeroReels cannot find the active ComfyUI model folder yet. Open ComfyUI Desktop once, then use Setup → Detect / Select Data Folder.",
        )
        return

    root = normalize_comfy_base(root)
    expected_dir = root / "models" / subfolder
    expected_dir.mkdir(parents=True, exist_ok=True)

    filename, _ = QFileDialog.getOpenFileName(
        self,
        f"Select {label}",
        str(expected_dir if expected_dir.exists() else root),
        "SafeTensors model (*.safetensors);;All files (*.*)",
    )
    if not filename:
        return

    selected = Path(filename)
    if not selected.exists():
        QMessageBox.warning(self, "ZeroReels", "The selected file no longer exists.")
        return

    target = expected_dir / selected.name
    if not _same_path(selected, target):
        answer = QMessageBox.question(
            self,
            "Import model into ComfyUI",
            f"{selected.name} is outside ComfyUI's active {subfolder} folder.\n\n"
            f"Move it here so ComfyUI can load it?\n{target}\n\n"
            "Moving avoids creating another multi-gigabyte copy.",
            QMessageBox.Yes | QMessageBox.Cancel,
            QMessageBox.Yes,
        )
        if answer != QMessageBox.Yes:
            return

        try:
            if target.exists():
                _append_log(self, f"Using existing model in active ComfyUI folder: {target}")
            else:
                _append_log(self, f"Moving selected {label}: {selected}")
                _append_log(self, f"Destination: {target}")
                shutil.move(str(selected), str(target))
                _append_log(self, f"Moved: {target.name}")
            selected = target
        except Exception as exc:
            QMessageBox.critical(self, "ZeroReels", f"Could not move the selected model file:\n{exc}")
            return

    identifier = selected.relative_to(expected_dir).as_posix()
    setattr(self.settings, key, identifier)
    self.settings.comfy_root = str(root)
    self.settings.save()

    if hasattr(self, "setting_edits") and key in self.setting_edits:
        self.setting_edits[key].setText(identifier)

    _append_log(self, f"Selected {label}: {identifier}")
    _append_log(self, "Restart ComfyUI Desktop, then click Run Checks in Diagnostics.")
    if hasattr(self, "status_detail"):
        self.status_detail.setText(f"{label} selected. Restart ComfyUI, then run Diagnostics.")

    try:
        self._refresh_setup_summary()
        self._refresh_diagnostics()
    except Exception:
        pass

    QMessageBox.information(
        self,
        "Model selected",
        f"{label} is now set to:\n{identifier}\n\nRestart ComfyUI Desktop, then run Diagnostics.",
    )


def install() -> None:
    original_settings_page = ui.MainWindow._settings_page

    def _settings_page_with_model_browse(self):
        page = original_settings_page(self)
        for key in MODEL_FIELDS:
            edit = self.setting_edits.get(key)
            if edit is None:
                continue
            layout = edit.parentWidget().layout()
            if not isinstance(layout, QGridLayout):
                continue
            index = layout.indexOf(edit)
            if index < 0:
                continue
            row, _column, _row_span, _column_span = layout.getItemPosition(index)
            browse = ui.SoftButton("Browse")
            browse.clicked.connect(lambda checked=False, k=key: self._browse_comfy_model_file(k))
            layout.addWidget(browse, row, 2)
        return page

    ui.MainWindow._browse_comfy_model_file = _browse_comfy_model_file
    ui.MainWindow._settings_page = _settings_page_with_model_browse
