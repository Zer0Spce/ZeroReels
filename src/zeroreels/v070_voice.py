from __future__ import annotations

from pathlib import Path
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
import wave

from . import services
from .config import APP_DIR, Settings, VOICE_DIR
from .models import Project


DELIVERY_PROFILES = {
    "Natural Storyteller": {"speed": 0.97, "hook": 0.98, "landing": 0.93, "pause": 0.20},
    "Curious": {"speed": 0.98, "hook": 1.01, "landing": 0.94, "pause": 0.22},
    "Serious Documentary": {"speed": 0.94, "hook": 0.96, "landing": 0.91, "pause": 0.25},
    "Dark Mystery": {"speed": 0.91, "hook": 0.94, "landing": 0.88, "pause": 0.31},
    "Energetic Explainer": {"speed": 1.03, "hook": 1.06, "landing": 0.97, "pause": 0.15},
}


def _progress(progress, value: int, text: str) -> None:
    if progress:
        progress(value, text)


def _clean_spoken(text: str) -> str:
    value = " ".join((text or "").split()).strip()
    value = re.sub(r"\s+([,.;:!?])", r"\1", value)
    if value and value[-1] not in ".!?…":
        value += "."
    return value


def directed_script(project: Project, delivery: str) -> str:
    """Create one continuous narration performance without changing factual wording."""
    profile = DELIVERY_PROFILES.get(delivery, DELIVERY_PROFILES["Natural Storyteller"])
    parts: list[str] = []
    for i, scene in enumerate(project.scenes):
        text = _clean_spoken(scene.narration)
        if not text:
            continue
        role = scene.shot_role or ""
        # Punctuation is the only direction Kokoro reliably understands. We keep it subtle:
        # a stronger boundary after the hook/peak and a softer landing cadence at the end.
        if i == 0 or role == "Hook":
            text = re.sub(r"[.!?…]+$", ".", text)
        elif role in {"Peak", "Landing"}:
            text = re.sub(r"[.!?…]+$", "…", text)
        parts.append(text)
    separator = "  " if profile["pause"] <= 0.20 else "   "
    return separator.join(parts)


def _wav_duration(path: Path) -> float:
    try:
        with wave.open(str(path), "rb") as wav:
            return wav.getnframes() / float(wav.getframerate())
    except Exception:
        try:
            import soundfile as sf
            info = sf.info(str(path))
            return float(info.frames) / float(info.samplerate)
        except Exception as exc:
            raise RuntimeError(f"Could not measure narration WAV: {path}") from exc


def _scene_weights(project: Project, delivery: str) -> list[float]:
    profile = DELIVERY_PROFILES.get(delivery, DELIVERY_PROFILES["Natural Storyteller"])
    values: list[float] = []
    for scene in project.scenes:
        text = scene.narration or ""
        words = max(1, len(re.findall(r"\b[\w’'-]+\b", text)))
        punctuation = len(re.findall(r"[,;:—…]", text)) * 0.45 + len(re.findall(r"[.!?]", text)) * 0.75
        role_bonus = 0.0
        if scene.shot_role in {"Hook", "Peak"}:
            role_bonus = profile["pause"] * 1.4
        elif scene.shot_role == "Landing":
            role_bonus = profile["pause"] * 2.0
        values.append(words + punctuation + role_bonus)
    return values


def apply_scene_timing(project: Project, duration: float, delivery: str) -> None:
    weights = _scene_weights(project, delivery)
    total = sum(weights) or 1.0
    assigned = 0.0
    for i, (scene, weight) in enumerate(zip(project.scenes, weights)):
        if i == len(project.scenes) - 1:
            scene.duration = max(0.8, duration - assigned)
        else:
            scene.duration = max(0.8, duration * weight / total)
            assigned += scene.duration


def _kokoro_model(settings: Settings):
    model_path = Path(settings.kokoro_model_path).expanduser()
    voices_path = Path(settings.kokoro_voices_path).expanduser()
    if not model_path.exists() or not voices_path.exists():
        raise RuntimeError("Kokoro voice files are missing. Open Setup and download the local voice model first.")
    try:
        from kokoro_onnx import Kokoro
        return Kokoro(str(model_path), str(voices_path))
    except Exception as exc:
        raise RuntimeError(f"Could not load the Kokoro voice model: {exc}") from exc


class KokoroDirectedVoiceService:
    """One continuous Kokoro performance with delivery-aware cadence and scene timing."""

    def __init__(self, settings: Settings, delivery: str):
        self.settings = settings
        self.delivery = delivery

    def generate(self, project: Project, out_dir: Path, progress=None) -> Path:
        _progress(progress, 20, f"Voice Director • {self.delivery}")
        text = directed_script(project, self.delivery)
        if not text:
            raise RuntimeError("Narration is empty")
        profile = DELIVERY_PROFILES.get(self.delivery, DELIVERY_PROFILES["Natural Storyteller"])
        speed = max(0.78, min(1.18, float(self.settings.kokoro_speed) * float(profile["speed"])))
        model = _kokoro_model(self.settings)
        try:
            import soundfile as sf
            samples, sample_rate = model.create(
                text,
                voice=self.settings.kokoro_voice,
                speed=speed,
                lang=self.settings.kokoro_lang,
            )
            target = out_dir / "narration.wav"
            sf.write(str(target), samples, sample_rate, subtype="PCM_16")
        except Exception as exc:
            # Some Kokoro builds are happier with shorter inputs. Fall back to 2-scene blocks,
            # still substantially more continuous than the old one-scene-at-a-time delivery.
            _progress(progress, 22, "Long-form voice pass retried in natural blocks")
            parts: list[Path] = []
            for block_index in range(0, len(project.scenes), 2):
                block_scenes = project.scenes[block_index:block_index + 2]
                block_text = "  ".join(_clean_spoken(scene.narration) for scene in block_scenes)
                part = out_dir / f"voice_block_{block_index // 2 + 1:02d}.wav"
                try:
                    samples, sample_rate = model.create(
                        block_text,
                        voice=self.settings.kokoro_voice,
                        speed=speed,
                        lang=self.settings.kokoro_lang,
                    )
                    sf.write(str(part), samples, sample_rate, subtype="PCM_16")
                except Exception as block_exc:
                    raise RuntimeError(f"Kokoro Voice Director failed: {block_exc}") from block_exc
                parts.append(part)
            target = out_dir / "narration.wav"
            services._concat_wavs(parts, target, silence_seconds=float(profile["pause"]))
        if not target.exists() or target.stat().st_size < 1000:
            raise RuntimeError("Voice Director did not create a valid narration WAV")
        duration = _wav_duration(target)
        apply_scene_timing(project, duration, self.delivery)
        project.actual_seconds = round(duration, 2)
        project.voice_engine_used = "Kokoro Directed"
        project.voice_delivery = self.delivery
        _progress(progress, 29, f"Voice performance ready • {duration:.1f}s")
        return target


RUNNER_CHATTERBOX = r'''from pathlib import Path
import argparse
import torch
import torchaudio as ta
from chatterbox.tts_turbo import ChatterboxTurboTTS
p=argparse.ArgumentParser(); p.add_argument('--text-file'); p.add_argument('--ref'); p.add_argument('--out'); p.add_argument('--device', default='cpu')
a=p.parse_args(); text=Path(a.text_file).read_text(encoding='utf-8')
model=ChatterboxTurboTTS.from_pretrained(device=a.device, nano=True)
wav=model.generate(text, audio_prompt_path=a.ref)
ta.save(a.out, wav, model.sr)
'''

RUNNER_F5 = r'''from pathlib import Path
import argparse
from f5_tts.api import F5TTS
p=argparse.ArgumentParser(); p.add_argument('--text-file'); p.add_argument('--ref'); p.add_argument('--ref-text', default=''); p.add_argument('--out')
a=p.parse_args(); text=Path(a.text_file).read_text(encoding='utf-8')
model=F5TTS()
model.infer(ref_file=a.ref, ref_text=a.ref_text, gen_text=text, file_wave=a.out)
'''


class ExternalNaturalVoiceService:
    def __init__(self, settings: Settings, engine: str, delivery: str):
        self.settings = settings
        self.engine = engine
        self.delivery = delivery

    def _paths(self) -> tuple[Path, str]:
        if self.engine == "Chatterbox Nano":
            return Path(self.settings.chatterbox_python).expanduser(), RUNNER_CHATTERBOX
        return Path(self.settings.f5_python).expanduser(), RUNNER_F5

    def generate(self, project: Project, out_dir: Path, progress=None) -> Path:
        python_exe, runner_source = self._paths()
        if not python_exe.exists():
            raise RuntimeError(
                f"{self.engine} is not installed yet. Open Setup → Voice and install the optional Natural Voice engine."
            )
        ref = Path(self.settings.natural_voice_ref).expanduser() if self.settings.natural_voice_ref else None
        if not ref or not ref.exists():
            raise RuntimeError(
                f"{self.engine} needs a short reference voice WAV. Choose one in Settings → Natural voice reference."
            )
        _progress(progress, 20, f"Natural Voice • {self.engine} • {self.delivery}")
        text_path = out_dir / "voice_directed.txt"
        text_path.write_text(directed_script(project, self.delivery), encoding="utf-8")
        runner = out_dir / "_natural_voice_runner.py"
        runner.write_text(runner_source, encoding="utf-8")
        target = out_dir / "narration.wav"
        command = [str(python_exe), str(runner), "--text-file", str(text_path), "--ref", str(ref), "--out", str(target)]
        if self.engine == "Chatterbox Nano":
            # CPU is deliberate: it avoids fighting ComfyUI for VRAM on 6 GB class GPUs.
            command += ["--device", "cpu"]
        else:
            command += ["--ref-text", self.settings.natural_voice_ref_text or ""]
        proc = subprocess.run(command, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, timeout=1800)
        try:
            runner.unlink(missing_ok=True)
        except OSError:
            pass
        if proc.returncode != 0 or not target.exists() or target.stat().st_size < 1000:
            detail = (proc.stderr or proc.stdout or "unknown error")[-1800:]
            raise RuntimeError(f"{self.engine} generation failed:\n{detail}")
        duration = _wav_duration(target)
        apply_scene_timing(project, duration, self.delivery)
        project.actual_seconds = round(duration, 2)
        project.voice_engine_used = self.engine
        project.voice_delivery = self.delivery
        _progress(progress, 29, f"Natural Voice ready • {duration:.1f}s")
        return target


def voice_service_for(settings: Settings, engine: str, delivery: str, mock_mode: bool = False):
    if mock_mode:
        return services.MockVoiceService()
    if engine == "Kokoro Classic":
        return services.KokoroVoiceService(settings)
    if engine in {"Chatterbox Nano", "F5-TTS Studio"}:
        return ExternalNaturalVoiceService(settings, engine, delivery)
    return KokoroDirectedVoiceService(settings, delivery)


def rewrite_for_measured_duration(settings: Settings, project: Project, actual_seconds: float, progress=None) -> bool:
    target = float(project.target_seconds)
    if target <= 0 or actual_seconds <= 0:
        return False
    ratio = target / actual_seconds
    if 0.95 <= ratio <= 1.05:
        return False
    _progress(progress, 31, f"Runtime lock • {actual_seconds:.1f}s → {target:.0f}s target")
    scene_count = len(project.scenes)
    schema = {
        "type": "object",
        "properties": {
            "scenes": {
                "type": "array",
                "minItems": scene_count,
                "maxItems": scene_count,
                "items": {"type": "object", "properties": {"narration": {"type": "string"}}, "required": ["narration"]},
            }
        },
        "required": ["scenes"],
    }
    draft = "\n".join(f"{i + 1}. {scene.narration}" for i, scene in enumerate(project.scenes))
    if actual_seconds < target:
        direction = f"Expand naturally by about {(target / actual_seconds - 1) * 100:.0f} percent. Deepen existing beats; do not add new factual claims."
    else:
        direction = f"Tighten naturally by about {(1 - target / actual_seconds) * 100:.0f} percent. Remove redundancy before useful meaning."
    prompt = f"""You are the final spoken-runtime editor for a short-form narration.

TOPIC: {project.topic}
STYLE: {project.style}
MEASURED AUDIO: {actual_seconds:.2f} seconds
TARGET AUDIO: {target:.2f} seconds
SCENES: exactly {scene_count}

{direction}

Rules:
- Rewrite narration only. Preserve facts, uncertainty, names, numbers and causal meaning.
- Keep each scene's existing purpose and order so its already-planned visual remains valid.
- Natural spoken English: contractions, varied sentence length, no essay tone.
- Do not repeat ideas or add generic filler.
- Hook immediately in scene 1; finish with one memorable landing line, no CTA.
- Return ONLY JSON matching the schema.

DRAFT:\n{draft}"""
    try:
        result = services._post_json(
            settings.ollama_url.rstrip("/") + "/api/generate",
            {
                "model": settings.ollama_model,
                "prompt": prompt,
                "stream": False,
                "format": schema,
                "think": False,
                "options": {"temperature": 0.34, "top_p": 0.90, "repeat_penalty": 1.12},
            },
            timeout=600,
        )
        data = json.loads(result["response"])
        rows = data.get("scenes", [])
        if len(rows) != scene_count:
            return False
        values = [" ".join(str(row.get("narration", "")).split()).strip() for row in rows]
        if not all(values):
            return False
        for scene, text in zip(project.scenes, values):
            scene.narration = text
        project.script = " ".join(values)
        project.runtime_rewrites += 1
        _progress(progress, 32, "Runtime rewrite ready • re-performing narration")
        return True
    except Exception:
        _progress(progress, 32, "Runtime rewrite skipped • keeping usable narration")
        return False


def _run_streamed(command: list[str], progress=None, base: int = 5, span: int = 85) -> None:
    proc = subprocess.Popen(command, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True, errors="replace")
    lines = 0
    tail: list[str] = []
    assert proc.stdout is not None
    for raw in proc.stdout:
        line = raw.strip()
        if not line:
            continue
        lines += 1
        tail.append(line)
        tail = tail[-10:]
        if progress:
            progress(min(92, base + min(span, lines // 2)), line[-180:])
    code = proc.wait()
    if code != 0:
        raise RuntimeError("\n".join(tail[-8:]) or f"Installer exited with code {code}")


def _find_python_311() -> list[str] | None:
    py = shutil.which("py")
    if py:
        test = subprocess.run([py, "-3.11", "-c", "import sys; print(sys.version_info[:2])"], capture_output=True, text=True)
        if test.returncode == 0:
            return [py, "-3.11"]
    for name in ("python3.11", "python"):
        exe = shutil.which(name)
        if not exe:
            continue
        test = subprocess.run([exe, "-c", "import sys; raise SystemExit(0 if sys.version_info[:2]==(3,11) else 1)"])
        if test.returncode == 0:
            return [exe]
    local = Path(os.environ.get("LOCALAPPDATA", "")) / "Programs" / "Python" / "Python311" / "python.exe"
    if local.exists():
        return [str(local)]
    return None


def install_optional_voice_engine(settings: Settings, engine: str, progress=None) -> None:
    if engine not in {"Chatterbox Nano", "F5-TTS Studio"}:
        raise ValueError(engine)
    _progress(progress, 2, f"Preparing {engine} environment")
    python_cmd = _find_python_311()
    if not python_cmd and shutil.which("winget"):
        _progress(progress, 4, "Installing Python 3.11 for the isolated Natural Voice environment")
        _run_streamed([
            shutil.which("winget") or "winget", "install", "-e", "--id", "Python.Python.3.11",
            "--accept-package-agreements", "--accept-source-agreements", "--silent",
        ], progress, 4, 18)
        python_cmd = _find_python_311()
    if not python_cmd:
        raise RuntimeError("Python 3.11 could not be found. Install Python 3.11, then retry this optional voice engine setup.")

    key = "chatterbox" if engine == "Chatterbox Nano" else "f5"
    root = VOICE_DIR / key
    venv_python = root / "Scripts" / "python.exe"
    root.parent.mkdir(parents=True, exist_ok=True)
    if not venv_python.exists():
        _progress(progress, 12, f"Creating isolated {engine} environment")
        subprocess.run(python_cmd + ["-m", "venv", str(root)], check=True)
    _progress(progress, 20, "Updating pip")
    _run_streamed([str(venv_python), "-m", "pip", "install", "--upgrade", "pip"], progress, 20, 12)
    package = "chatterbox-tts" if engine == "Chatterbox Nano" else "f5-tts"
    _progress(progress, 34, f"Installing {package} (large first-time download)")
    _run_streamed([str(venv_python), "-m", "pip", "install", package], progress, 34, 56)
    if engine == "Chatterbox Nano":
        settings.chatterbox_python = str(venv_python)
    else:
        settings.f5_python = str(venv_python)
    settings.save()
    _progress(progress, 100, f"{engine} installed. Model weights download automatically on first use.")
