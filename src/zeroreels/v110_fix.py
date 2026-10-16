from __future__ import annotations

from dataclasses import replace
from pathlib import Path

from PySide6.QtWidgets import QLabel

from . import pipeline, services, ui, v110_cloud


_PREVIOUS_RUN = None
_PREVIOUS_MAKE_PROJECT = None
_PREVIOUS_SETTINGS_PAGE = None


def make_project_v110(self):
    mode = self.script_mode_box.currentText() if hasattr(self, "script_mode_box") else "ChatGPT Script"
    custom = self.custom_script_editor.toPlainText().strip() if hasattr(self, "custom_script_editor") else ""
    restore_topic = None
    if mode == "Custom Script" and custom and not self.topic.toPlainText().strip():
        restore_topic = ""
        self.topic.setPlainText(" ".join(custom.split()[:12]).strip(" .,!?:;-") or "Custom narration")
    try:
        project = _PREVIOUS_MAKE_PROJECT(self)
    finally:
        if restore_topic is not None:
            self.topic.setPlainText(restore_topic)
    project.script_mode = mode
    project.custom_script = custom
    project.script_model_mode = "OpenAI"
    return project


def run_v110(self, project, options, progress=lambda value, text: None):
    """Give OpenAI Images the same automatic online-video B-roll path as local AI images."""
    if bool(getattr(options, "mock_mode", False)) or getattr(options, "image_source_mode", "") != "OpenAI Images":
        return _PREVIOUS_RUN(self, project, options, progress)

    old_service = services.ComfyImageService
    services.ComfyImageService = v110_cloud.OpenAIImageService
    v110_cloud._OPENAI_IMAGE_ACTIVE = True
    try:
        local_shape = replace(options, image_source_mode="AI Generated")
        # v110's previous pipeline is the v0.10 video-aware pipeline. Calling it directly avoids
        # the v110 wrapper re-reading the temporary mode and lets v0.10 select motion B-roll.
        result = v110_cloud._PREVIOUS_PIPELINE_RUN(self, project, local_shape, progress)
        result.image_source_mode = "OpenAI Images"
        if result.output_dir:
            result.save(Path(result.output_dir) / "project.json")
        return result
    finally:
        services.ComfyImageService = old_service
        v110_cloud._OPENAI_IMAGE_ACTIVE = False


def settings_page_v110_fix(self):
    page = _PREVIOUS_SETTINGS_PAGE(self)
    # Ollama no longer participates in scripting. Remove the obsolete fields from the visible UI
    # while retaining backward-compatible config keys for old project/settings files.
    for label in page.findChildren(QLabel):
        if label.text() in {"Ollama URL", "Ollama model"}:
            label.hide()
    for key in ("ollama_url", "ollama_model"):
        edit = getattr(self, "setting_edits", {}).get(key)
        if edit is not None:
            edit.hide()
    return page


def install() -> None:
    global _PREVIOUS_RUN, _PREVIOUS_MAKE_PROJECT, _PREVIOUS_SETTINGS_PAGE
    _PREVIOUS_RUN = pipeline.Pipeline.run
    _PREVIOUS_MAKE_PROJECT = ui.MainWindow._make_project
    _PREVIOUS_SETTINGS_PAGE = ui.MainWindow._settings_page

    pipeline.Pipeline.run = run_v110
    ui.MainWindow._make_project = make_project_v110
    ui.MainWindow._settings_page = settings_page_v110_fix
    # ui.py imported diagnostics by value, so patch that reference too.
    ui.diagnostics = v110_cloud.cloud_diagnostics
