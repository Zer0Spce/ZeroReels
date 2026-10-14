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


def _choose_comfy_root(self, start: Path | None = None) -> Path | None:
    """Let the user explicitly choose the active models folder when auto-detect fails."""
    folder = QFileDialog.getExistingDirectory(
        self,
        "Select ACTIVE ComfyUI models folder (or the folder containing models)",
        str(start or Path.home()),
    )
    if not folder:
        return None
    selected = Path(folder)
    if selected.name.lower() == "models":
        root = selected.parent
    elif (selected / "models").exists():
        root = selected
    else:
        QMessageBox.warning(
            self,
            "ZeroReels",
            "That folder is not a ComfyUI model location. Select the 'models' folder itself, or its parent folder.",
        )
        return None
    return root


def _browse_comfy_model_file(self, key: str) -> None:
    if key not in MODEL_FIELDS:
        return

    label, subfolder = MODEL_FIELDS[key]

    # Browse the actual file FIRST. The Browse button must remain useful even if
    # Comfy Desktop auto-detection is what is currently broken.
    detected = detect_comfy_root()
    saved = normalize_comfy_base(self.settings.comfy_root) if self.settings.comfy_root else None
    initial_root = detected or saved
    start = Path.home()
    if initial_root:
        candidate = initial_root / "models" / subfolder
        if candidate.exists():
            start = candidate

    filename, _ = QFileDialog.getOpenFileName(
        self,
        f"Select {label}",
        str(start),
        "SafeTensors model (*.safetensors);;All files (*.*)",
    )
    if not filename:
        return

    selected = Path(filename)
    if not selected.exists():
        QMessageBox.warning(self, "ZeroReels", "The selected file no longer exists.")
        return

    # Re-run detection after the picker. Current Comfy Desktop installations.json
    # is authoritative. If that still cannot be found, ask for the active models
    # folder directly rather than blocking the user in a detection loop.
    root = detect_comfy_root()
    if not root:
        inferred_start = selected.parent.parent if selected.parent.parent.exists() else selected.parent
        root = _choose_comfy_root(self, inferred_start)
        if not root:
            return

    root = normalize_comfy_base(root)
    expected_dir = root / "models" / subfolder
    expected_dir.mkdir(parents=True, exist_ok=True)
    target = expected_dir / selected.name

    if not _same_path(selected, target):
        answer = QMessageBox.question(
            self,
            "Import model into active ComfyUI",
            f"ZeroReels will move this file into the model folder used by the active ComfyUI installation.\n\n"
            f"From:\n{selected}\n\n"
            f"To:\n{target}\n\n"
            "Move it now? This avoids making another multi-gigabyte copy.",
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

    if hasattr(self, "setting_edits"):
        if key in self.setting_edits:
            self.setting_edits[key].setText(identifier)
        if "comfy_root" in self.setting_edits:
            self.setting_edits["comfy_root"].setText(str(root))

    _append_log(self, f"Active ComfyUI root: {root}")
    _append_log(self, f"Selected {label}: {identifier}")
    _append_log(self, f"Verified file location: {selected}")
    _append_log(self, "Restart ComfyUI Desktop, then click Run Checks in Diagnostics.")
    if hasattr(self, "status_detail"):
        self.status_detail.setText(f"{label} imported. Restart ComfyUI, then run Diagnostics.")

    try:
        self._refresh_setup_summary()
        self._refresh_diagnostics()
    except Exception:
        pass

    QMessageBox.information(
        self,
        "Model imported",
        f"{label} is now in the active ComfyUI model folder:\n\n{selected}\n\n"
        "Fully close and reopen ComfyUI Desktop, then run Diagnostics.",
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
