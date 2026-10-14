from __future__ import annotations

from pathlib import Path
from typing import Callable
import os
import shutil
import subprocess
import urllib.request

from .config import Settings, detect_comfy_root, find_executable, is_comfy_program_install_root

Progress = Callable[[int, str], None]
Log = Callable[[str], None]


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


def _emit(log: Log | None, text: str) -> None:
    if log and text:
        log(text.rstrip())


def _same_path(a: Path, b: Path) -> bool:
    aa = str(a.resolve(strict=False))
    bb = str(b.resolve(strict=False))
    return aa.lower() == bb.lower() if os.name == "nt" else aa == bb


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


def _run_stream(cmd: list[str], log: Log | None = None, timeout: int | None = None) -> str:
    flags = subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0
    _emit(log, "> " + subprocess.list2cmdline(cmd))
    proc = subprocess.Popen(
        cmd,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
        encoding="utf-8",
        errors="replace",
        bufsize=1,
        creationflags=flags,
    )
    lines: list[str] = []
    try:
        assert proc.stdout is not None
        for raw in iter(proc.stdout.readline, ""):
            line = raw.rstrip("\r\n")
            if line:
                lines.append(line)
                _emit(log, line)
        proc.wait(timeout=timeout)
    except subprocess.TimeoutExpired:
        proc.kill()
        proc.wait()
        raise RuntimeError("Command timed out")
    finally:
        if proc.stdout:
            proc.stdout.close()
    output = "\n".join(lines)
    if proc.returncode != 0:
        raise RuntimeError((output or f"Command failed with exit code {proc.returncode}")[-3000:])
    return output


def winget_available() -> bool:
    return bool(shutil.which("winget"))


def install_winget_package(package_id: str, log: Log | None = None) -> None:
    if not winget_available():
        raise RuntimeError("Windows Package Manager (winget) is not available on this PC.")
    _emit(log, f"Installing {package_id} with Windows Package Manager...")
    _run_stream([
        "winget", "install", "--id", package_id, "-e",
        "--accept-package-agreements", "--accept-source-agreements",
        "--silent", "--disable-interactivity",
    ], log=log, timeout=1800)
    _emit(log, f"{package_id} install command completed successfully.")


def install_ollama(log: Log | None = None) -> None:
    install_winget_package("Ollama.Ollama", log=log)


def install_comfyui(log: Log | None = None) -> None:
    install_winget_package("Comfy.ComfyUI-Desktop", log=log)


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


def pull_ollama_model(model: str, progress: Progress | None = None, log: Log | None = None) -> None:
    if progress:
        progress(10, f"Pulling {model} with Ollama")
    _emit(log, f"Downloading script model: {model}")
    _run_stream([_ollama_exe(), "pull", model], log=log, timeout=7200)
    if progress:
        progress(100, f"{model} is ready")
    _emit(log, f"Script model ready: {model}")


def download_kokoro_models(settings: Settings, progress: Progress | None = None, log: Log | None = None) -> None:
    model_path = Path(settings.kokoro_model_path).expanduser()
    voices_path = Path(settings.kokoro_voices_path).expanduser()
    _download(KOKORO_MODEL_URL, model_path, progress, 5, 88, "Kokoro voice model", min_existing_bytes=50_000_000, log=log)
    _download(KOKORO_VOICES_URL, voices_path, progress, 89, 99, "Kokoro voice pack", min_existing_bytes=5_000_000, log=log)
    if progress:
        progress(100, "Kokoro voice is ready")
    _emit(log, "Kokoro voice files are ready.")


def resolve_comfy_root(settings: Settings, log: Log | None = None) -> Path:
    detected = detect_comfy_root()
    saved = Path(settings.comfy_root).expanduser() if settings.comfy_root else None

    # ComfyUI Desktop's own configured basePath is authoritative. This also repairs
    # older ZeroReels versions that accidentally saved the application install folder.
    if detected:
        if saved and not _same_path(saved, detected):
            _emit(log, f"Correcting ComfyUI data folder: {saved} -> {detected}")
        settings.comfy_root = str(detected)
        settings.save()
        return detected

    if saved and saved.exists() and not is_comfy_program_install_root(saved):
        return saved

    if saved and is_comfy_program_install_root(saved):
        raise RuntimeError(
            "The selected ComfyUI folder is the application install folder, not the model/data folder. "
            "Open ComfyUI Desktop once, finish its first-time setup, then click Detect / Select Data Folder again."
        )

    raise RuntimeError(
        "ZeroReels could not find the ComfyUI data folder. Open ComfyUI Desktop once, "
        "finish its first-time setup, then use Detect / Select Data Folder in ZeroReels Setup."
    )


def _download(
    url: str, target: Path, progress: Progress | None, start_pct: int, end_pct: int, label: str,
    min_existing_bytes: int = 50_000_000, log: Log | None = None,
) -> None:
    target.parent.mkdir(parents=True, exist_ok=True)
    if target.exists() and target.stat().st_size >= min_existing_bytes:
        if progress:
            progress(end_pct, f"{label} already exists")
        _emit(log, f"Already present: {target}")
        return
    temp = target.with_suffix(target.suffix + ".part")
    req = urllib.request.Request(url, headers={"User-Agent": "ZeroReels/0.4"})
    _emit(log, f"Downloading {label}")
    _emit(log, f"Target: {target}")
    try:
        with urllib.request.urlopen(req, timeout=60) as response, temp.open("wb") as out:
            total = int(response.headers.get("Content-Length") or 0)
            done = 0
            last_log_bucket = -1
            while True:
                chunk = response.read(4 * 1024 * 1024)
                if not chunk:
                    break
                out.write(chunk)
                done += len(chunk)
                if total:
                    ratio = min(1.0, done / total)
                    pct = start_pct + int((end_pct - start_pct) * ratio)
                    if progress:
                        if total >= 1024**3:
                            progress(pct, f"Downloading {label} — {done / (1024**3):.1f}/{total / (1024**3):.1f} GB")
                        else:
                            progress(pct, f"Downloading {label} — {done / (1024**2):.0f}/{total / (1024**2):.0f} MB")
                    bucket = int(ratio * 10)
                    if bucket != last_log_bucket:
                        last_log_bucket = bucket
                        _emit(log, f"{label}: {int(ratio * 100)}%")
        temp.replace(target)
        _emit(log, f"Completed: {target.name}")
    except Exception:
        if temp.exists():
            temp.unlink(missing_ok=True)
        raise


def _migrate_existing_flux_models(old_root: Path | None, new_root: Path, log: Log | None = None) -> None:
    if not old_root or not old_root.exists() or _same_path(old_root, new_root):
        return
    for label, _url, relative in FLUX_MODELS:
        source = old_root / relative
        target = new_root / relative
        if not source.exists() or target.exists():
            continue
        target.parent.mkdir(parents=True, exist_ok=True)
        _emit(log, f"Moving existing {label} into active ComfyUI model folder...")
        _emit(log, f"From: {source}")
        _emit(log, f"To:   {target}")
        shutil.move(str(source), str(target))
        _emit(log, f"Moved: {target.name}")


def download_flux_models(settings: Settings, progress: Progress | None = None, log: Log | None = None) -> Path:
    old_root = Path(settings.comfy_root).expanduser() if settings.comfy_root else None
    root = resolve_comfy_root(settings, log=log)
    _emit(log, f"Using ComfyUI data folder: {root}")

    # Avoid making the user download ~15 GB again when an older ZeroReels version
    # wrote the model pack into the ComfyUI application directory by mistake.
    _migrate_existing_flux_models(old_root, root, log=log)

    spans = [(4, 32), (34, 91), (92, 99)]
    for (label, url, relative), (start, end) in zip(FLUX_MODELS, spans):
        _download(url, root / relative, progress, start, end, label, log=log)
    if progress:
        progress(100, "FLUX.2 Klein model pack is ready. Restart ComfyUI if it is already open.")
    _emit(log, "FLUX.2 Klein model pack is ready in ComfyUI's active model folder.")
    _emit(log, "Restart ComfyUI Desktop, then click Run Checks in ZeroReels Diagnostics.")
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
