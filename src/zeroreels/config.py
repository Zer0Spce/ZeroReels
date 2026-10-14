from __future__ import annotations

from dataclasses import asdict, dataclass
from pathlib import Path
import json
import shutil


APP_DIR = Path.home() / ".zeroreels"
SETTINGS_FILE = APP_DIR / "settings.json"
PROJECTS_DIR = APP_DIR / "projects"


@dataclass(slots=True)
class Settings:
    ollama_url: str = "http://127.0.0.1:11434"
    ollama_model: str = "qwen2.5:7b"
    comfy_url: str = "http://127.0.0.1:8188"
    comfy_workflow: str = ""
    piper_exe: str = "piper"
    piper_model: str = ""
    whisper_exe: str = "whisper-cli"
    whisper_model: str = ""
    ffmpeg_exe: str = ""

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


def find_executable(configured: str, name: str) -> str | None:
    if configured:
        path = Path(configured).expanduser()
        if path.exists():
            return str(path)
    return shutil.which(name)
