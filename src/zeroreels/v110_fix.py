from __future__ import annotations

from dataclasses import replace
from pathlib import Path

from PySide6.QtWidgets import QLabel

from . import pipeline, services, ui, v110_cloud
from .config import find_executable


_PREVIOUS_RUN = None
_PREVIOUS_MAKE_PROJECT = None
_PREVIOUS_SETTINGS_PAGE = None
_PREVIOUS_GENERATE = None


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


def diagnostics_v110(settings):
    """Cloud-first diagnostics. Local image/voice engines are optional until selected."""
    rows: list[tuple[str, bool, str]] = []
    openai = bool(v110_cloud.get_secret(v110_cloud.OPENAI_SECRET))
    eleven = bool(v110_cloud.get_secret(v110_cloud.ELEVEN_SECRET))
    cloud = v110_cloud.load_cloud_settings()
    rows.append(("OpenAI / ChatGPT", openai, f"{cloud.openai_text_model} • {'connected' if openai else 'connect in Settings'}"))
    rows.append(("OpenAI Images", True, f"{cloud.openai_image_model} • {'available' if openai else 'optional • connect OpenAI to use'}"))
    rows.append(("ElevenLabs", True, f"{cloud.eleven_voice_name or cloud.eleven_voice_id} • {'connected' if eleven else 'optional • not connected'}"))

    try:
        info = services._get_json(settings.comfy_url.rstrip("/") + "/object_info", timeout=3)
        node_ok = "Flux2Scheduler" in info and "EmptyFlux2LatentImage" in info
        rows.append(("Local ComfyUI (optional)", True, settings.comfy_url + (" • ready" if node_ok else " • update needed if selected")))
        rows.append(("Local FLUX models (optional)", True, "ready" if node_ok else "not required when using OpenAI Images"))
    except Exception:
        rows.append(("Local ComfyUI (optional)", True, "offline • not required when using OpenAI Images"))
        rows.append(("Local FLUX models (optional)", True, "not checked"))

    model = Path(settings.kokoro_model_path).expanduser()
    voices = Path(settings.kokoro_voices_path).expanduser()
    kokoro_ready = model.exists() and voices.exists()
    rows.append(("Local Kokoro (optional)", True, "ready" if kokoro_ready else "not installed • ElevenLabs can be used instead"))

    ffmpeg = find_executable(settings.ffmpeg_exe, "ffmpeg")
    if not ffmpeg:
        try:
            import imageio_ffmpeg
            ffmpeg = imageio_ffmpeg.get_ffmpeg_exe()
        except Exception:
            ffmpeg = None
    rows.append(("FFmpeg", bool(ffmpeg), ffmpeg or "Not found"))
    return rows


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
    # Direct Create Speech support is guaranteed for Eleven v4 and Flash v2.5. Keep the UI on
    # those stable paths instead of exposing the realtime/WebSocket-specific Turbo transport.
    box = getattr(self, "eleven_model_box", None)
    if box is not None:
        index = box.findData("eleven_v4_turbo")
        if index >= 0:
            box.removeItem(index)
    return page


def generate_v110_fix(self):
    # Test Mode intentionally bypasses cloud credentials so developers can still smoke-test the UI.
    if getattr(self, "test_mode", None) is not None and self.test_mode.isChecked():
        return v110_cloud._PREVIOUS_GENERATE(self)
    return _PREVIOUS_GENERATE(self)


def install() -> None:
    global _PREVIOUS_RUN, _PREVIOUS_MAKE_PROJECT, _PREVIOUS_SETTINGS_PAGE, _PREVIOUS_GENERATE
    _PREVIOUS_RUN = pipeline.Pipeline.run
    _PREVIOUS_MAKE_PROJECT = ui.MainWindow._make_project
    _PREVIOUS_SETTINGS_PAGE = ui.MainWindow._settings_page
    _PREVIOUS_GENERATE = ui.MainWindow._generate

    pipeline.Pipeline.run = run_v110
    ui.MainWindow._make_project = make_project_v110
    ui.MainWindow._settings_page = settings_page_v110_fix
    ui.MainWindow._generate = generate_v110_fix
    services.diagnostics = diagnostics_v110
    # ui.py imported diagnostics by value, so patch that reference too.
    ui.diagnostics = diagnostics_v110
