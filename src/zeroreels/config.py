from __future__ import annotations

from dataclasses import asdict, dataclass
from pathlib import Path
import json
import os
import shutil


APP_DIR = Path.home() / ".zeroreels"
SETTINGS_FILE = APP_DIR / "settings.json"
PROJECTS_DIR = APP_DIR / "projects"
TTS_DIR = APP_DIR / "tts"


@dataclass(slots=True)
class Settings:
    ollama_url: str = "http://127.0.0.1:11434"
    ollama_model: str = "qwen3:4b"
    comfy_url: str = "http://127.0.0.1:8188"
    comfy_root: str = ""
    comfy_unet: str = "flux-2-klein-4b.safetensors"
    comfy_clip: str = "qwen_3_4b.safetensors"
    comfy_vae: str = "flux2-vae.safetensors"
    kokoro_model_path: str = str(TTS_DIR / "kokoro-v1.0.onnx")
    kokoro_voices_path: str = str(TTS_DIR / "voices-v1.0.bin")
    kokoro_voice: str = "af_heart"
    kokoro_speed: float = 1.0
    kokoro_lang: str = "en-us"
    ffmpeg_exe: str = ""
    music_dir: str = ""
    transition_seconds: float = 0.35

    def save(self) -> None:
        APP_DIR.mkdir(parents=True, exist_ok=True)
        SETTINGS_FILE.write_text(json.dumps(asdict(self), indent=2), encoding="utf-8")

    @classmethod
    def load(cls) -> "Settings":
        if not SETTINGS_FILE.exists():
            return cls()
        try:
            data = json.loads(SETTINGS_FILE.read_text(encoding="utf-8"))
            allowed = cls.__dataclass_fields__.keys()
            return cls(**{k: v for k, v in data.items() if k in allowed})
        except Exception:
            return cls()


def dimensions_for(fmt: str) -> tuple[int, int]:
    return {"9:16": (1080, 1920), "16:9": (1920, 1080), "1:1": (1080, 1080)}.get(fmt, (1080, 1920))


def generation_dimensions_for(fmt: str) -> tuple[int, int]:
    # Generation resolution is deliberately lower than final output resolution.
    # FFmpeg scales to delivery size after AI generation, saving VRAM substantially.
    return {"9:16": (768, 1344), "16:9": (1344, 768), "1:1": (1024, 1024)}.get(fmt, (768, 1344))


def find_executable(configured: str, name: str) -> str | None:
    if configured:
        path = Path(configured).expanduser()
        if path.exists():
            return str(path)
    return shutil.which(name)


def detect_comfy_root() -> Path | None:
    candidates: list[Path] = []
    home = Path.home()
    candidates += [
        home / "ComfyUI-Shared",
        home / "Documents" / "ComfyUI",
        home / "ComfyUI",
    ]

    appdata = Path(os.environ.get("APPDATA", home / "AppData" / "Roaming"))
    config_file = appdata / "ComfyUI" / "config.json"
    if config_file.exists():
        try:
            data = json.loads(config_file.read_text(encoding="utf-8"))
            for key in ("basePath", "base_path", "modelBasePath", "sharedModelsPath"):
                value = data.get(key)
                if value:
                    candidates.insert(0, Path(value).expanduser())
        except Exception:
            pass

    for candidate in candidates:
        if (candidate / "models").exists():
            return candidate
    return None
