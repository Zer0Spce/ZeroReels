from __future__ import annotations

from pathlib import Path

from PySide6.QtWidgets import QLabel

from . import services, ui
from .browser_ai import CHATGPT_IMAGE_SOURCE, ELEVEN_BROWSER_ENGINE
from .browser_sessions import find_chrome_executable, service_status
from .config import find_executable


def diagnostics_v111(settings):
    rows: list[tuple[str, bool, str]] = []

    chrome = find_chrome_executable()
    rows.append(("Google Chrome", bool(chrome), chrome or "Install Google Chrome or set CHROME_PATH"))

    chat = service_status("chatgpt")
    rows.append((
        "ChatGPT Browser Profile",
        chat["status"] == "verified",
        f"{chat['status']} • {chat['message']}",
    ))

    eleven = service_status("elevenlabs")
    eleven_selected = getattr(settings, "voice_engine", "") in {ELEVEN_BROWSER_ENGINE, "ElevenLabs Cloud"}
    rows.append((
        "ElevenLabs Browser Profile",
        (not eleven_selected) or eleven["status"] == "verified",
        f"{eleven['status']} • {'selected voice engine' if eleven_selected else 'optional until selected'}",
    ))

    image_mode = getattr(settings, "image_source_mode", "AI Generated")
    if image_mode == "OpenAI Images":
        image_mode = CHATGPT_IMAGE_SOURCE
    local_images_required = image_mode in {"AI Generated", "Hybrid"}
    try:
        info = services._get_json(settings.comfy_url.rstrip("/") + "/object_info", timeout=3)
        node_ok = "Flux2Scheduler" in info and "EmptyFlux2LatentImage" in info
        rows.append((
            "Local ComfyUI / FLUX",
            node_ok if local_images_required else True,
            ("ready" if node_ok else "update/install required") if local_images_required else ("available" if node_ok else "optional • not selected"),
        ))
    except Exception:
        rows.append((
            "Local ComfyUI / FLUX",
            not local_images_required,
            "offline • required for selected visual mode" if local_images_required else "offline • optional",
        ))

    kokoro_selected = getattr(settings, "voice_engine", "Kokoro Directed") in {"Kokoro Directed", "Kokoro Classic"}
    model = Path(settings.kokoro_model_path).expanduser()
    voices = Path(settings.kokoro_voices_path).expanduser()
    kokoro_ready = model.exists() and voices.exists()
    rows.append((
        "Local Kokoro",
        kokoro_ready if kokoro_selected else True,
        "ready" if kokoro_ready else ("voice files required for selected engine" if kokoro_selected else "optional • not selected"),
    ))

    ffmpeg = find_executable(settings.ffmpeg_exe, "ffmpeg")
    if not ffmpeg:
        try:
            import imageio_ffmpeg
            ffmpeg = imageio_ffmpeg.get_ffmpeg_exe()
        except Exception:
            ffmpeg = None
    rows.append(("FFmpeg", bool(ffmpeg), ffmpeg or "Not found"))
    return rows


def install() -> None:
    services.diagnostics = diagnostics_v111
    ui.diagnostics = diagnostics_v111

    original_sidebar = ui.MainWindow._sidebar

    def sidebar(self):
        self.setWindowTitle("ZeroReels — Browser + Local AI Video Automation")
        frame = original_sidebar(self)
        for label in frame.findChildren(QLabel):
            if label.text().startswith("v0."):
                label.setText("v0.11.1 BROWSER")
                label.setMaximumWidth(152)
                break
        return frame

    ui.MainWindow._sidebar = sidebar
