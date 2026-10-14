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
    """Normalize a ComfyUI path to the base directory that owns the models folder."""
    candidate = Path(path).expanduser()
    if candidate.name.lower() == "models":
        candidate = candidate.parent
    return candidate


def _unique_paths(paths: list[Path]) -> list[Path]:
    unique: list[Path] = []
    seen: set[str] = set()
    for path in paths:
        try:
            resolved = path.resolve(strict=False)
        except Exception:
            resolved = path
        key = str(resolved).lower() if os.name == "nt" else str(resolved)
        if key not in seen:
            seen.add(key)
            unique.append(path)
    return unique


def _modern_desktop_user_data_dirs() -> list[Path]:
    """Locations used by current Comfy Desktop builds for installations.json."""
    home = Path.home()
    appdata = Path(os.environ.get("APPDATA", home / "AppData" / "Roaming"))
    candidates = [
        appdata / "comfyui-desktop-2",
        appdata / "ComfyUI",
        appdata / "Comfy Desktop",
        appdata / "comfyui-electron",
    ]
    try:
        for child in appdata.iterdir():
            if child.is_dir() and "comfy" in child.name.lower():
                candidates.append(child)
    except Exception:
        pass
    return _unique_paths(candidates)


def _record_last_launched(record: dict) -> float:
    values: list[float] = []
    raw = record.get("lastLaunchedAt")
    if isinstance(raw, (int, float)):
        values.append(float(raw))
    per_category = record.get("lastLaunchedAtByCategory")
    if isinstance(per_category, dict):
        for value in per_category.values():
            if isinstance(value, (int, float)):
                values.append(float(value))
    return max(values, default=0.0)


def _modern_comfy_install_roots() -> list[Path]:
    """Return real ComfyUI roots from current Comfy Desktop installation records.

    Current Comfy Desktop stores one or more installations in installations.json.
    Each installation has its own ComfyUI directory and built-in models folder.
    That folder is always visible to the running ComfyUI instance and is safer for
    ZeroReels than guessing the Electron application's Program Files directory.
    """
    roots: list[Path] = []
    records: list[dict] = []

    for data_dir in _modern_desktop_user_data_dirs():
        path = data_dir / "installations.json"
        if not path.exists():
            continue
        try:
            parsed = json.loads(path.read_text(encoding="utf-8"))
        except Exception:
            continue
        if isinstance(parsed, list):
            records.extend(item for item in parsed if isinstance(item, dict))

    records.sort(key=_record_last_launched, reverse=True)

    for record in records:
        status = str(record.get("status") or "installed").lower()
        if status in {"failed", "installing"}:
            continue
        raw_install = record.get("installPath")
        if not isinstance(raw_install, str) or not raw_install.strip():
            continue
        install_path = _expanded_path(raw_install.strip())

        # Comfy Desktop's own helper resolves the ComfyUI root from installPath;
        # in normal installs this is <installPath>/ComfyUI, while imported/manual
        # installs can already point at the ComfyUI root itself.
        candidates = [install_path / "ComfyUI", install_path]
        try:
            for child in install_path.iterdir():
                if child.is_dir() and child.name.lower() == "comfyui":
                    candidates.insert(0, child)
        except Exception:
            pass

        for candidate in _unique_paths(candidates):
            if (candidate / "models").exists():
                roots.append(candidate)
                break

    return _unique_paths(roots)


def _comfy_desktop_config_roots() -> list[Path]:
    """Return roots configured by legacy/older ComfyUI Desktop builds."""
    home = Path.home()
    appdata = Path(os.environ.get("APPDATA", home / "AppData" / "Roaming"))
    config_dir = appdata / "ComfyUI"
    roots: list[Path] = []

    config_file = config_dir / "config.json"
    if config_file.exists():
        try:
            data = json.loads(config_file.read_text(encoding="utf-8"))
            for key in ("basePath", "base_path", "modelBasePath", "sharedModelsPath"):
                value = data.get(key)
                if isinstance(value, str) and value.strip():
                    roots.append(normalize_comfy_base(_expanded_path(value.strip())))
        except Exception:
            pass

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

    return _unique_paths(roots)


def is_comfy_program_install_root(path: str | Path) -> bool:
    """True for the Electron app install directory, not an actual ComfyUI instance."""
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
    """Detect the real ComfyUI root whose models folder the running Desktop install scans."""
    home = Path.home()

    # Current Comfy Desktop: use installations.json and the most recently launched
    # actual ComfyUI install. This must win over stale legacy config.json values.
    modern = _modern_comfy_install_roots()
    if modern:
        return modern[0]

    # Older Desktop builds.
    for candidate in _comfy_desktop_config_roots():
        candidate = normalize_comfy_base(candidate)
        if (candidate / "models").exists() and not is_comfy_program_install_root(candidate):
            return candidate

    # Portable/manual installs.
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
