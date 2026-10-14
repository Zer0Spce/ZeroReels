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


def _expanded_path(value: str) -> Path:
    return Path(os.path.expandvars(value)).expanduser()


def normalize_comfy_base(path: str | Path) -> Path:
    """Normalize a ComfyUI path to the base directory that owns the models folder.

    ComfyUI Desktop may expose either its base directory or the models directory itself.
    ZeroReels stores the base directory because model paths are appended as models/....
    """
    candidate = Path(path).expanduser()
    if candidate.name.lower() == "models":
        candidate = candidate.parent
    return candidate


def _comfy_desktop_config_roots() -> list[Path]:
    """Return roots explicitly configured by ComfyUI Desktop, highest priority first."""
    home = Path.home()
    appdata = Path(os.environ.get("APPDATA", home / "AppData" / "Roaming"))
    config_dir = appdata / "ComfyUI"
    roots: list[Path] = []

    config_file = config_dir / "config.json"
    if config_file.exists():
        try:
            data = json.loads(config_file.read_text(encoding="utf-8"))
            # Desktop versions have used several names. Some point to a base path,
            # while others point directly at the models folder; normalize both.
            for key in ("basePath", "base_path", "modelBasePath", "sharedModelsPath"):
                value = data.get(key)
                if isinstance(value, str) and value.strip():
                    roots.append(normalize_comfy_base(_expanded_path(value.strip())))
        except Exception:
            pass

    # Some Desktop versions also persist the selected model root in YAML.
    for yaml_name in ("extra_models_config.yaml", "extra_model_paths.yaml"):
        yaml_file = config_dir / yaml_name
        if not yaml_file.exists():
            continue
        try:
            for raw in yaml_file.read_text(encoding="utf-8", errors="replace").splitlines():
                line = raw.strip()
                if not line or line.startswith("#") or ":" not in line:
                    continue
                key, value = line.split(":", 1)
                if key.strip() in {"base_path", "basePath"}:
                    cleaned = value.strip().strip("'\"")
                    if cleaned:
                        roots.append(normalize_comfy_base(_expanded_path(cleaned)))
        except Exception:
            pass

    # Preserve order while removing duplicates (case-insensitive on Windows).
    unique: list[Path] = []
    seen: set[str] = set()
    for root in roots:
        key = str(root.resolve(strict=False)).lower() if os.name == "nt" else str(root.resolve(strict=False))
        if key not in seen:
            seen.add(key)
            unique.append(root)
    return unique


def is_comfy_program_install_root(path: str | Path) -> bool:
    """True when a path is the Desktop application install directory, not its user data root."""
    try:
        root = normalize_comfy_base(path).resolve(strict=False)
        localappdata = Path(os.environ.get("LOCALAPPDATA", "")).resolve(strict=False)
        programs = localappdata / "Programs"
        root_text = str(root).lower()
        programs_text = str(programs).lower()
        return root_text.startswith(programs_text + os.sep.lower()) and "comfy" in root.name.lower()
    except Exception:
        return False


def detect_comfy_root() -> Path | None:
    """Detect the base directory whose models folder ComfyUI Desktop actually scans."""
    home = Path.home()

    # First use ComfyUI Desktop's own authoritative configuration.
    for candidate in _comfy_desktop_config_roots():
        candidate = normalize_comfy_base(candidate)
        if (candidate / "models").exists():
            return candidate

    # Fallbacks for portable/manual installs.
    candidates = [
        home / "ComfyUI-Shared",
        home / "Documents" / "ComfyUI",
        home / "ComfyUI",
    ]
    for candidate in candidates:
        candidate = normalize_comfy_base(candidate)
        if (candidate / "models").exists() and not is_comfy_program_install_root(candidate):
            return candidate
    return None
