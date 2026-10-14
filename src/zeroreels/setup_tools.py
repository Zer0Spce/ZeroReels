from __future__ import annotations

from pathlib import Path
from typing import Callable
import os
import shutil
import subprocess
import urllib.request

from .config import Settings, detect_comfy_root, find_executable

Progress = Callable[[int, str], None]


KOKORO_MODEL_URL = "https://github.com/thewh1teagle/kokoro-onnx/releases/download/model-files-v1.1/kokoro-v1.0.onnx"
KOKORO_VOICES_URL = "https://github.com/thewh1teagle/kokoro-onnx/releases/download/model-files-v1.1/voices-v1.0.bin"

FLUX_MODELS = (
    (
        "text encoder",
        "https://huggingface.co/Comfy-Org/flux2-klein/resolve/main/split_files/text_encoders/qwen_3_4b.safetensors",
        Path("models/text_encoders/qwen_3_4b.safetensors"),
    ),
    (
        "diffusion model",
        "https://huggingface.co/Comfy-Org/flux2-klein/resolve/main/split_files/diffusion_models/flux-2-klein-4b.safetensors",
        Path("models/diffusion_models/flux-2-klein-4b.safetensors"),
    ),
    (
        "VAE",
        "https://huggingface.co/Comfy-Org/flux2-dev/resolve/main/split_files/vae/flux2-vae.safetensors",
        Path("models/vae/flux2-vae.safetensors"),
    ),
)


def _run(cmd: list[str], timeout: int | None = None) -> str:
    flags = subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0
    proc = subprocess.run(
        cmd,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
        encoding="utf-8",
        errors="replace",
        timeout=timeout,
        creationflags=flags,
    )
    if proc.returncode != 0:
        raise RuntimeError((proc.stdout or "Command failed")[-2500:])
    return proc.stdout or ""


def winget_available() -> bool:
    return bool(shutil.which("winget"))


def install_winget_package(package_id: str) -> None:
    if not winget_available():
        raise RuntimeError("Windows Package Manager (winget) is not available on this PC.")
    _run([
        "winget", "install", "--id", package_id, "-e",
        "--accept-package-agreements", "--accept-source-agreements",
        "--silent", "--disable-interactivity",
    ], timeout=1800)


def install_ollama() -> None:
    install_winget_package("Ollama.Ollama")


def install_comfyui() -> None:
    install_winget_package("Comfy.ComfyUI-Desktop")


def _ollama_exe() -> str:
    exe = find_executable("", "ollama")
    if exe:
        return exe
    candidates = [
        Path(os.environ.get("LOCALAPPDATA", "")) / "Programs/Ollama/ollama.exe",
        Path.home() / "AppData/Local/Programs/Ollama/ollama.exe",
    ]
    for candidate in candidates:
        if candidate.exists():
            return str(candidate)
    raise RuntimeError("Ollama is not installed yet. Use Install Ollama first.")


def pull_ollama_model(model: str, progress: Progress | None = None) -> None:
    if progress:
        progress(10, f"Pulling {model} with Ollama")
    _run([_ollama_exe(), "pull", model], timeout=7200)
    if progress:
        progress(100, f"{model} is ready")


def download_kokoro_models(settings: Settings, progress: Progress | None = None) -> None:
    model_path = Path(settings.kokoro_model_path).expanduser()
    voices_path = Path(settings.kokoro_voices_path).expanduser()
    _download(KOKORO_MODEL_URL, model_path, progress, 5, 88, "Kokoro voice model", min_existing_bytes=50_000_000)
    _download(KOKORO_VOICES_URL, voices_path, progress, 89, 99, "Kokoro voice pack", min_existing_bytes=5_000_000)
    if progress:
        progress(100, "Kokoro voice is ready")


def resolve_comfy_root(settings: Settings) -> Path:
    if settings.comfy_root:
        root = Path(settings.comfy_root).expanduser()
        if root.exists():
            return root
    detected = detect_comfy_root()
    if detected:
        settings.comfy_root = str(detected)
        settings.save()
        return detected
    raise RuntimeError(
        "ZeroReels could not find the ComfyUI data folder. Open ComfyUI Desktop once, "
        "then use Select ComfyUI Folder in ZeroReels Setup."
    )


def _download(
    url: str, target: Path, progress: Progress | None, start_pct: int, end_pct: int, label: str,
    min_existing_bytes: int = 50_000_000,
) -> None:
    target.parent.mkdir(parents=True, exist_ok=True)
    if target.exists() and target.stat().st_size >= min_existing_bytes:
        if progress:
            progress(end_pct, f"{label} already exists")
        return
    temp = target.with_suffix(target.suffix + ".part")
    req = urllib.request.Request(url, headers={"User-Agent": "ZeroReels/0.4"})
    try:
        with urllib.request.urlopen(req, timeout=60) as response, temp.open("wb") as out:
            total = int(response.headers.get("Content-Length") or 0)
            done = 0
            while True:
                chunk = response.read(4 * 1024 * 1024)
                if not chunk:
                    break
                out.write(chunk)
                done += len(chunk)
                if progress and total:
                    ratio = min(1.0, done / total)
                    pct = start_pct + int((end_pct - start_pct) * ratio)
                    
                    if total >= 1024**3:
                        progress(pct, f"Downloading {label} — {done / (1024**3):.1f}/{total / (1024**3):.1f} GB")
                    else:
                        progress(pct, f"Downloading {label} — {done / (1024**2):.0f}/{total / (1024**2):.0f} MB")
        temp.replace(target)
    except Exception:
        if temp.exists():
            temp.unlink(missing_ok=True)
        raise


def download_flux_models(settings: Settings, progress: Progress | None = None) -> Path:
    root = resolve_comfy_root(settings)
    spans = [(4, 32), (34, 91), (92, 99)]
    for (label, url, relative), (start, end) in zip(FLUX_MODELS, spans):
        _download(url, root / relative, progress, start, end, label)
    if progress:
        progress(100, "FLUX.2 Klein model pack is ready. Restart ComfyUI if it is already open.")
    return root


def gpu_summary() -> str:
    nvidia = shutil.which("nvidia-smi")
    if nvidia:
        try:
            text = _run([
                nvidia,
                "--query-gpu=name,memory.total",
                "--format=csv,noheader,nounits",
            ], timeout=10).strip()
            if text:
                name, _, memory = text.partition(",")
                return f"{name.strip()} — {memory.strip()} MB VRAM"
        except Exception:
            pass
    return "No NVIDIA GPU detected by nvidia-smi (ComfyUI may still use another supported backend)."
