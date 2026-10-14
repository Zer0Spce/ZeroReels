from __future__ import annotations

from pathlib import Path
from typing import Callable
import json
import math
import os
import random
import shutil
import struct
import subprocess
import time
import urllib.parse
import urllib.request
import wave

from .config import Settings, dimensions_for, find_executable
from .models import Project, Scene

Progress = Callable[[int, str], None]


def _post_json(url: str, payload: dict, timeout: int = 300) -> dict:
    req = urllib.request.Request(
        url,
        data=json.dumps(payload).encode("utf-8"),
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    with urllib.request.urlopen(req, timeout=timeout) as response:
        return json.loads(response.read().decode("utf-8"))


class ScriptService:
    def __init__(self, settings: Settings):
        self.settings = settings

    def generate(self, project: Project, scene_count: int) -> tuple[str, list[Scene]]:
        prompt = f"""Create a short-form video script about: {project.topic}
Style: {project.style}
Target length: about {project.target_seconds} seconds.
Return strict JSON only with keys title, script, scenes.
scenes must contain exactly {scene_count} objects with narration and image_prompt.
Make scene prompts visually consistent, specific, safe, and without text overlays.
Use a strong opening hook and a satisfying ending."""
        result = _post_json(
            self.settings.ollama_url.rstrip("/") + "/api/generate",
            {"model": self.settings.ollama_model, "prompt": prompt, "stream": False, "format": "json"},
        )
        data = json.loads(result["response"])
        raw_scenes = data.get("scenes", [])[:scene_count]
        if not raw_scenes:
            raise RuntimeError("Ollama returned no scenes")
        duration = max(2.0, project.target_seconds / len(raw_scenes))
        scenes = [
            Scene(i + 1, s.get("narration", ""), s.get("image_prompt", ""), duration)
            for i, s in enumerate(raw_scenes)
        ]
        return data.get("script", "\n".join(s.narration for s in scenes)), scenes


class MockScriptService:
    def generate(self, project: Project, scene_count: int) -> tuple[str, list[Scene]]:
        scene_count = max(3, scene_count)
        duration = max(2.0, project.target_seconds / scene_count)
        scenes: list[Scene] = []
        for i in range(scene_count):
            beat = i + 1
            narration = (
                f"Scene {beat}: {project.topic}. "
                + ("Here is the hook that pulls the viewer in." if i == 0 else "The story moves forward with one clear visual beat.")
                + (" This closes with a memorable final thought." if i == scene_count - 1 else "")
            )
            image_prompt = f"{project.style}, scene {beat}, {project.topic}, cinematic composition, detailed lighting, no text, consistent visual identity"
            scenes.append(Scene(beat, narration, image_prompt, duration))
        return " ".join(s.narration for s in scenes), scenes


class MockImageService:
    def generate(self, scene: Scene, out_dir: Path, fmt: str) -> Path:
        width, height = dimensions_for(fmt)
        # Small proxy images keep Mock Mode quick while preserving the target aspect ratio.
        scale = max(width, height) / 720
        w, h = max(240, int(width / scale)), max(240, int(height / scale))
        path = out_dir / f"scene_{scene.index:03d}.ppm"
        seed = abs(hash(scene.image_prompt)) % 255
        r = 28 + seed % 70
        g = 38 + (seed * 3) % 65
        b = 56 + (seed * 7) % 70
        with path.open("wb") as f:
            f.write(f"P6\n{w} {h}\n255\n".encode())
            row = bytes((r, g, b)) * w
            for y in range(h):
                # Gentle vertical luminance variation makes motion easier to see.
                shift = int(18 * y / max(1, h - 1))
                rr, gg, bb = min(255, r + shift), min(255, g + shift), min(255, b + shift)
                f.write(bytes((rr, gg, bb)) * w)
        return path


class ComfyImageService:
    def __init__(self, settings: Settings):
        self.settings = settings

    def generate(self, scene: Scene, out_dir: Path, fmt: str) -> Path:
        workflow_path = Path(self.settings.comfy_workflow).expanduser()
        if not workflow_path.exists():
            raise RuntimeError("Set a ComfyUI API workflow JSON in Settings")
        width, height = dimensions_for(fmt)
        raw = workflow_path.read_text(encoding="utf-8")
        raw = raw.replace("{{PROMPT}}", scene.image_prompt.replace('"', '\\"'))
        raw = raw.replace("{{WIDTH}}", str(width)).replace("{{HEIGHT}}", str(height))
        raw = raw.replace("{{SEED}}", str(random.randint(1, 2_147_483_647)))
        workflow = json.loads(raw)
        base = self.settings.comfy_url.rstrip("/")
        queued = _post_json(base + "/prompt", {"prompt": workflow})
        prompt_id = queued["prompt_id"]
        history = None
        for _ in range(600):
            with urllib.request.urlopen(base + "/history/" + prompt_id, timeout=10) as response:
                data = json.loads(response.read().decode("utf-8"))
            history = data.get(prompt_id)
            if history:
                break
            time.sleep(1)
        if not history:
            raise RuntimeError("ComfyUI generation timed out")
        image_info = None
        for output in history.get("outputs", {}).values():
            images = output.get("images", [])
            if images:
                image_info = images[0]
                break
        if not image_info:
            raise RuntimeError("ComfyUI completed without an output image")
        params = urllib.parse.urlencode({
            "filename": image_info["filename"],
            "subfolder": image_info.get("subfolder", ""),
            "type": image_info.get("type", "output"),
        })
        suffix = Path(image_info["filename"]).suffix or ".png"
        target = out_dir / f"scene_{scene.index:03d}{suffix}"
        with urllib.request.urlopen(base + "/view?" + params, timeout=120) as response:
            target.write_bytes(response.read())
        return target


class MockVoiceService:
    def generate(self, project: Project, out_dir: Path) -> Path:
        duration = max(2.0, sum(s.duration for s in project.scenes))
        path = out_dir / "narration.wav"
        rate = 22050
        amplitude = 900
        with wave.open(str(path), "w") as wav:
            wav.setparams((1, 2, rate, int(rate * duration), "NONE", "not compressed"))
            for i in range(int(rate * duration)):
                # Very quiet test tone; enough to verify muxing without pretending to be narration.
                sample = int(amplitude * math.sin(2 * math.pi * 180 * i / rate))
                wav.writeframesraw(struct.pack("<h", sample))
        return path


class PiperVoiceService:
    def __init__(self, settings: Settings):
        self.settings = settings

    def generate(self, project: Project, out_dir: Path) -> Path:
        exe = find_executable(self.settings.piper_exe, "piper")
        if not exe or not self.settings.piper_model:
            raise RuntimeError("Configure Piper executable and voice model in Settings")
        path = out_dir / "narration.wav"
        text = "\n".join(scene.narration for scene in project.scenes)
        proc = subprocess.run(
            [exe, "--model", self.settings.piper_model, "--output_file", str(path)],
            input=text.encode("utf-8"), stdout=subprocess.PIPE, stderr=subprocess.PIPE,
        )
        if proc.returncode != 0:
            raise RuntimeError(proc.stderr.decode("utf-8", errors="replace")[-1200:])
        return path


class CaptionService:
    def generate_from_scenes(self, project: Project, out_dir: Path) -> Path:
        path = out_dir / "captions.srt"
        cursor = 0.0
        chunks: list[str] = []
        for i, scene in enumerate(project.scenes, start=1):
            start, end = cursor, cursor + scene.duration
            chunks.append(f"{i}\n{self._stamp(start)} --> {self._stamp(end)}\n{scene.narration}\n")
            cursor = end
        path.write_text("\n".join(chunks), encoding="utf-8")
        return path

    @staticmethod
    def _stamp(seconds: float) -> str:
        ms = int(round(seconds * 1000))
        h, ms = divmod(ms, 3_600_000)
        m, ms = divmod(ms, 60_000)
        s, ms = divmod(ms, 1000)
        return f"{h:02d}:{m:02d}:{s:02d},{ms:03d}"


class WhisperCaptionService:
    def __init__(self, settings: Settings):
        self.settings = settings

    def generate(self, audio: Path, out_dir: Path) -> Path:
        exe = find_executable(self.settings.whisper_exe, "whisper-cli")
        if not exe or not self.settings.whisper_model:
            raise RuntimeError("Configure whisper.cpp executable and model in Settings")
        prefix = out_dir / "captions"
        proc = subprocess.run(
            [exe, "-m", self.settings.whisper_model, "-f", str(audio), "-osrt", "-of", str(prefix)],
            stdout=subprocess.PIPE, stderr=subprocess.PIPE,
        )
        if proc.returncode != 0:
            raise RuntimeError(proc.stderr.decode("utf-8", errors="replace")[-1200:])
        return prefix.with_suffix(".srt")


class FFmpegRenderer:
    def __init__(self, settings: Settings):
        self.settings = settings

    def _ffmpeg(self) -> str:
        configured = find_executable(self.settings.ffmpeg_exe, "ffmpeg")
        if configured:
            return configured
        try:
            import imageio_ffmpeg
            return imageio_ffmpeg.get_ffmpeg_exe()
        except Exception as exc:
            raise RuntimeError("FFmpeg was not found") from exc

    def render(self, project: Project, audio: Path, captions: Path | None, out_dir: Path, motion: bool = True) -> Path:
        ffmpeg = self._ffmpeg()
        concat = out_dir / "scenes.ffconcat"
        lines = ["ffconcat version 1.0"]
        for scene in project.scenes:
            image = Path(scene.image_path).resolve().as_posix().replace("'", "'\\''")
            lines.extend([f"file '{image}'", f"duration {scene.duration:.3f}"])
        if project.scenes:
            last = Path(project.scenes[-1].image_path).resolve().as_posix().replace("'", "'\\''")
            lines.append(f"file '{last}'")
        concat.write_text("\n".join(lines), encoding="utf-8")
        width, height = dimensions_for(project.format)
        vf = f"scale={width}:{height}:force_original_aspect_ratio=increase,crop={width}:{height},fps=30"
        if motion:
            vf += f",zoompan=z='min(zoom+0.00035,1.06)':d=1:s={width}x{height}:fps=30"
        output = out_dir / "final.mp4"
        cmd = [
            ffmpeg, "-y", "-safe", "0", "-f", "concat", "-i", str(concat),
            "-i", str(audio), "-vf", vf,
            "-c:v", "libx264", "-preset", "veryfast", "-crf", "21", "-pix_fmt", "yuv420p",
            "-c:a", "aac", "-b:a", "160k", "-shortest", "-movflags", "+faststart", str(output),
        ]
        proc = subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
        if proc.returncode != 0:
            raise RuntimeError("FFmpeg render failed:\n" + proc.stderr.decode("utf-8", errors="replace")[-1800:])
        return output


def diagnostics(settings: Settings) -> list[tuple[str, bool, str]]:
    rows: list[tuple[str, bool, str]] = []
    for label, configured, fallback in [
        ("Piper", settings.piper_exe, "piper"),
        ("whisper.cpp", settings.whisper_exe, "whisper-cli"),
        ("FFmpeg", settings.ffmpeg_exe, "ffmpeg"),
    ]:
        resolved = find_executable(configured, fallback)
        rows.append((label, bool(resolved), resolved or "Not found"))
    for label, url in [("Ollama", settings.ollama_url), ("ComfyUI", settings.comfy_url)]:
        try:
            with urllib.request.urlopen(url, timeout=1.5) as response:
                rows.append((label, response.status < 500, url))
        except Exception:
            rows.append((label, False, url + " (offline)"))
    try:
        import imageio_ffmpeg
        bundled = imageio_ffmpeg.get_ffmpeg_exe()
        rows.append(("Bundled FFmpeg fallback", bool(bundled), bundled))
    except Exception:
        rows.append(("Bundled FFmpeg fallback", False, "Unavailable"))
    return rows
