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
import urllib.error
import urllib.parse
import urllib.request
import wave

from .config import Settings, dimensions_for, find_executable, generation_dimensions_for
from .models import Project, Scene

Progress = Callable[[int, str], None]


def _post_json(url: str, payload: dict, timeout: int = 300) -> dict:
    req = urllib.request.Request(
        url,
        data=json.dumps(payload).encode("utf-8"),
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=timeout) as response:
            return json.loads(response.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        body = exc.read().decode("utf-8", errors="replace")
        raise RuntimeError(f"HTTP {exc.code} from {url}: {body[-1200:]}") from exc
    except urllib.error.URLError as exc:
        raise RuntimeError(f"Cannot connect to {url}. Is the local service running?") from exc


def _get_json(url: str, timeout: int = 15) -> dict:
    try:
        with urllib.request.urlopen(url, timeout=timeout) as response:
            return json.loads(response.read().decode("utf-8"))
    except urllib.error.URLError as exc:
        raise RuntimeError(f"Cannot connect to {url}. Is the local service running?") from exc


class ScriptService:
    def __init__(self, settings: Settings):
        self.settings = settings

    def generate(self, project: Project, scene_count: int) -> tuple[str, list[Scene]]:
        schema = {
            "type": "object",
            "properties": {
                "title": {"type": "string"},
                "script": {"type": "string"},
                "scenes": {
                    "type": "array",
                    "minItems": scene_count,
                    "maxItems": scene_count,
                    "items": {
                        "type": "object",
                        "properties": {
                            "narration": {"type": "string"},
                            "image_prompt": {"type": "string"},
                        },
                        "required": ["narration", "image_prompt"],
                    },
                },
            },
            "required": ["title", "script", "scenes"],
        }
        prompt = f"""Create a polished short-form video about: {project.topic}

Visual style: {project.style}
Target narration length: approximately {project.target_seconds} seconds.
Create exactly {scene_count} scenes.

Requirements:
- Start with a strong hook in scene 1.
- Keep narration concise and natural for voice-over.
- Each scene must advance the story or explanation.
- End with a satisfying final beat, not a generic filler CTA.
- image_prompt must describe only the visual scene, with consistent characters/setting/style across scenes.
- Image prompts must not request captions, logos, watermarks, UI, or text inside the image.
- Keep claims factual when the topic is factual; do not invent specific statistics, quotes, or events.
- Return only data matching the provided JSON schema.
"""
        endpoint = self.settings.ollama_url.rstrip("/") + "/api/generate"
        result = _post_json(
            endpoint,
            {
                "model": self.settings.ollama_model,
                "prompt": prompt,
                "stream": False,
                "format": schema,
                "think": False,
                "options": {"temperature": 0.25},
            },
            timeout=600,
        )
        try:
            data = json.loads(result["response"])
        except Exception as exc:
            raise RuntimeError("Ollama returned invalid structured output") from exc

        raw_scenes = data.get("scenes", [])
        if len(raw_scenes) != scene_count:
            raise RuntimeError(f"Ollama returned {len(raw_scenes)} scenes; expected {scene_count}")

        provisional = max(2.0, project.target_seconds / scene_count)
        scenes = [
            Scene(
                index=i + 1,
                narration=str(item.get("narration", "")).strip(),
                image_prompt=str(item.get("image_prompt", "")).strip(),
                duration=provisional,
            )
            for i, item in enumerate(raw_scenes)
        ]
        if any(not scene.narration or not scene.image_prompt for scene in scenes):
            raise RuntimeError("Ollama returned an incomplete scene")
        project.title = str(data.get("title") or project.topic).strip()[:100]
        script = str(data.get("script") or "\n".join(scene.narration for scene in scenes)).strip()
        return script, scenes


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
            image_prompt = (
                f"{project.style}, scene {beat}, {project.topic}, cinematic composition, "
                "detailed lighting, no text, consistent visual identity"
            )
            scenes.append(Scene(beat, narration, image_prompt, duration))
        project.title = project.topic.strip()[:100] or "Untitled Reel"
        return " ".join(s.narration for s in scenes), scenes


class MockImageService:
    def generate(self, scene: Scene, out_dir: Path, fmt: str) -> Path:
        width, height = generation_dimensions_for(fmt)
        scale = max(width, height) / 720
        w, h = max(240, int(width / scale)), max(240, int(height / scale))
        path = out_dir / f"scene_{scene.index:03d}.ppm"
        seed = abs(hash(scene.image_prompt)) % 255
        r, g, b = 28 + seed % 70, 38 + (seed * 3) % 65, 56 + (seed * 7) % 70
        with path.open("wb") as f:
            f.write(f"P6\n{w} {h}\n255\n".encode())
            for y in range(h):
                shift = int(18 * y / max(1, h - 1))
                rr, gg, bb = min(255, r + shift), min(255, g + shift), min(255, b + shift)
                f.write(bytes((rr, gg, bb)) * w)
        return path


class ComfyImageService:
    def __init__(self, settings: Settings):
        self.settings = settings

    def _workflow(self, prompt: str, fmt: str) -> dict:
        width, height = generation_dimensions_for(fmt)
        seed = random.randint(1, 2_147_483_647)
        s = self.settings
        return {
            "1": {"class_type": "UNETLoader", "inputs": {"unet_name": s.comfy_unet, "weight_dtype": "default"}},
            "2": {"class_type": "CLIPLoader", "inputs": {"clip_name": s.comfy_clip, "type": "flux2", "device": "default"}},
            "3": {"class_type": "VAELoader", "inputs": {"vae_name": s.comfy_vae}},
            "4": {"class_type": "CLIPTextEncode", "inputs": {"text": prompt, "clip": ["2", 0]}},
            "5": {"class_type": "ConditioningZeroOut", "inputs": {"conditioning": ["4", 0]}},
            "6": {"class_type": "CFGGuider", "inputs": {"model": ["1", 0], "positive": ["4", 0], "negative": ["5", 0], "cfg": 1.0}},
            "7": {"class_type": "RandomNoise", "inputs": {"noise_seed": seed}},
            "8": {"class_type": "KSamplerSelect", "inputs": {"sampler_name": "euler"}},
            "9": {"class_type": "Flux2Scheduler", "inputs": {"steps": 4, "width": width, "height": height}},
            "10": {"class_type": "EmptyFlux2LatentImage", "inputs": {"width": width, "height": height, "batch_size": 1}},
            "11": {
                "class_type": "SamplerCustomAdvanced",
                "inputs": {
                    "noise": ["7", 0],
                    "guider": ["6", 0],
                    "sampler": ["8", 0],
                    "sigmas": ["9", 0],
                    "latent_image": ["10", 0],
                },
            },
            "12": {"class_type": "VAEDecode", "inputs": {"samples": ["11", 0], "vae": ["3", 0]}},
            "13": {"class_type": "SaveImage", "inputs": {"filename_prefix": "ZeroReels", "images": ["12", 0]}},
        }

    def validate_server(self) -> None:
        base = self.settings.comfy_url.rstrip("/")
        info = _get_json(base + "/object_info", timeout=20)
        required = {
            "UNETLoader", "CLIPLoader", "VAELoader", "CLIPTextEncode", "ConditioningZeroOut", "CFGGuider",
            "RandomNoise", "KSamplerSelect", "Flux2Scheduler", "EmptyFlux2LatentImage",
            "SamplerCustomAdvanced", "VAEDecode", "SaveImage",
        }
        missing_nodes = sorted(required.difference(info))
        if missing_nodes:
            raise RuntimeError(
                "ComfyUI is running but is too old for FLUX.2 Klein. "
                f"Missing nodes: {', '.join(missing_nodes)}. Update ComfyUI Desktop."
            )

        def choices(node: str, field: str) -> list[str]:
            try:
                value = info[node]["input"]["required"][field][0]
                return value if isinstance(value, list) else []
            except Exception:
                return []

        model_checks = [
            ("diffusion model", self.settings.comfy_unet, choices("UNETLoader", "unet_name")),
            ("text encoder", self.settings.comfy_clip, choices("CLIPLoader", "clip_name")),
            ("VAE", self.settings.comfy_vae, choices("VAELoader", "vae_name")),
        ]
        missing = [f"{label}: {name}" for label, name, available in model_checks if available and name not in available]
        if missing:
            raise RuntimeError(
                "ComfyUI is missing the ZeroReels FLUX.2 model pack:\n- " + "\n- ".join(missing)
            )

    def generate(self, scene: Scene, out_dir: Path, fmt: str) -> Path:
        base = self.settings.comfy_url.rstrip("/")
        if scene.index == 1:
            self.validate_server()
        queued = _post_json(base + "/prompt", {"prompt": self._workflow(scene.image_prompt, fmt)}, timeout=30)
        prompt_id = queued.get("prompt_id")
        if not prompt_id:
            raise RuntimeError(f"ComfyUI rejected the prompt: {queued}")

        history = None
        deadline = time.time() + 900
        while time.time() < deadline:
            data = _get_json(base + "/history/" + urllib.parse.quote(prompt_id), timeout=15)
            history = data.get(prompt_id)
            if history:
                status = history.get("status", {})
                if status.get("status_str") == "error":
                    raise RuntimeError(f"ComfyUI generation failed: {status}")
                if history.get("outputs"):
                    break
            time.sleep(1.0)

        if not history or not history.get("outputs"):
            raise RuntimeError("ComfyUI generation timed out")

        image_info = None
        for output in history["outputs"].values():
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
        with urllib.request.urlopen(base + "/view?" + params, timeout=180) as response:
            target.write_bytes(response.read())
        return target


class MockVoiceService:
    def generate(self, project: Project, out_dir: Path, progress: Progress | None = None) -> Path:
        duration = max(2.0, sum(s.duration for s in project.scenes))
        path = out_dir / "narration.wav"
        rate, amplitude = 22050, 700
        with wave.open(str(path), "w") as wav:
            wav.setparams((1, 2, rate, int(rate * duration), "NONE", "not compressed"))
            for i in range(int(rate * duration)):
                sample = int(amplitude * math.sin(2 * math.pi * 180 * i / rate))
                wav.writeframesraw(struct.pack("<h", sample))
        return path


def _wav_duration(path: Path) -> float:
    with wave.open(str(path), "rb") as wav:
        return wav.getnframes() / float(wav.getframerate())


def _concat_wavs(parts: list[Path], target: Path, silence_seconds: float = 0.12) -> None:
    if not parts:
        raise RuntimeError("No narration audio was generated")
    with wave.open(str(parts[0]), "rb") as first:
        params = first.getparams()
    with wave.open(str(target), "wb") as out:
        out.setparams(params)
        silence_frames = int(params.framerate * silence_seconds)
        silence = b"\x00" * silence_frames * params.nchannels * params.sampwidth
        for index, part in enumerate(parts):
            with wave.open(str(part), "rb") as src:
                if (
                    src.getnchannels() != params.nchannels
                    or src.getsampwidth() != params.sampwidth
                    or src.getframerate() != params.framerate
                ):
                    raise RuntimeError("Voice engine produced inconsistent WAV formats")
                out.writeframes(src.readframes(src.getnframes()))
            if index != len(parts) - 1:
                out.writeframes(silence)


class KokoroVoiceService:
    def __init__(self, settings: Settings):
        self.settings = settings

    def generate(self, project: Project, out_dir: Path, progress: Progress | None = None) -> Path:
        model_path = Path(self.settings.kokoro_model_path).expanduser()
        voices_path = Path(self.settings.kokoro_voices_path).expanduser()
        if not model_path.exists() or not voices_path.exists():
            raise RuntimeError("Kokoro voice files are missing. Open Setup and download the local voice model first.")

        try:
            import soundfile as sf
            from kokoro_onnx import Kokoro
        except Exception as exc:
            raise RuntimeError("Kokoro voice engine is not installed correctly. Run setup.bat again.") from exc

        try:
            kokoro = Kokoro(str(model_path), str(voices_path))
        except Exception as exc:
            raise RuntimeError(f"Could not load the Kokoro voice model: {exc}") from exc

        parts: list[Path] = []
        pause = 0.12
        for i, scene in enumerate(project.scenes):
            if progress:
                progress(64 + int(8 * i / max(1, len(project.scenes))), f"Voice-over scene {i + 1} of {len(project.scenes)}")
            path = out_dir / f"voice_{scene.index:03d}.wav"
            try:
                samples, sample_rate = kokoro.create(
                    scene.narration,
                    voice=self.settings.kokoro_voice,
                    speed=float(self.settings.kokoro_speed),
                    lang=self.settings.kokoro_lang,
                )
                sf.write(str(path), samples, sample_rate, subtype="PCM_16")
            except Exception as exc:
                raise RuntimeError(
                    "Kokoro voice-over failed. Check the selected voice and local model files in Setup/Settings.\n"
                    + str(exc)
                ) from exc
            if not path.exists() or path.stat().st_size < 1000:
                raise RuntimeError("Kokoro did not create a valid narration WAV file")
            scene.audio_path = str(path)
            scene.duration = max(1.0, _wav_duration(path) + (pause if i != len(project.scenes) - 1 else 0.0))
            parts.append(path)

        target = out_dir / "narration.wav"
        _concat_wavs(parts, target, silence_seconds=pause)
        return target


class CaptionService:
    def generate_from_scenes(self, project: Project, out_dir: Path) -> Path:
        path = out_dir / "captions.srt"
        cursor = 0.0
        entries: list[str] = []
        caption_index = 1
        for scene in project.scenes:
            words = " ".join(scene.narration.split()).split()
            if not words:
                cursor += scene.duration
                continue
            # Short phrase captions are substantially easier to read on vertical video.
            groups = [words[i:i + 7] for i in range(0, len(words), 7)]
            weights = [max(1, len(group)) for group in groups]
            total_weight = sum(weights)
            used = 0.0
            for group, weight in zip(groups, weights):
                duration = scene.duration * weight / total_weight
                start = cursor + used
                end = min(cursor + scene.duration, start + duration)
                entries.append(
                    f"{caption_index}\n{self._stamp(start)} --> {self._stamp(end)}\n{' '.join(group)}\n"
                )
                caption_index += 1
                used += duration
            cursor += scene.duration
        path.write_text("\n".join(entries), encoding="utf-8")
        return path

    @staticmethod
    def _stamp(seconds: float) -> str:
        ms = int(round(seconds * 1000))
        h, ms = divmod(ms, 3_600_000)
        m, ms = divmod(ms, 60_000)
        s, ms = divmod(ms, 1000)
        return f"{h:02d}:{m:02d}:{s:02d},{ms:03d}"


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

    @staticmethod
    def _caption_filter() -> str:
        style = (
            "FontName=Segoe UI,FontSize=18,Bold=1,PrimaryColour=&H00FFFFFF,"
            "OutlineColour=&H90000000,BorderStyle=1,Outline=2,Shadow=0,"
            "Alignment=2,MarginV=90"
        )
        return f"subtitles=captions.srt:force_style='{style}'"

    def _scene_filter(self, scene_index: int, width: int, height: int, frames: int, motion: bool) -> str:
        base = f"scale={width}:{height}:force_original_aspect_ratio=increase,crop={width}:{height}"
        if not motion:
            return base + ",fps=30,format=yuv420p"
        if scene_index % 3 == 0:
            zp = "z='min(zoom+0.0007,1.07)':x='iw/2-(iw/zoom/2)':y='ih/2-(ih/zoom/2)'"
        elif scene_index % 3 == 1:
            zp = f"z='1.05':x='(iw-iw/zoom)*on/{max(1, frames)}':y='ih/2-(ih/zoom/2)'"
        else:
            zp = f"z='1.05':x='iw/2-(iw/zoom/2)':y='(ih-ih/zoom)*on/{max(1, frames)}'"
        return base + f",zoompan={zp}:d=1:s={width}x{height}:fps=30,format=yuv420p"

    def _render_scene_clips(
        self,
        project: Project,
        out_dir: Path,
        motion: bool,
        transitions: bool,
    ) -> list[Path]:
        ffmpeg = self._ffmpeg()
        width, height = dimensions_for(project.format)
        transition = max(0.05, min(float(self.settings.transition_seconds), 0.8))
        clips: list[Path] = []
        for i, scene in enumerate(project.scenes):
            duration = max(0.25, scene.duration)
            frames = max(1, int(round(duration * 30)))
            target = out_dir / f"_clip_{scene.index:03d}.mp4"
            vf = self._scene_filter(i, width, height, frames, motion)
            if transitions and duration > transition * 2:
                if i > 0:
                    vf += f",fade=t=in:st=0:d={transition:.3f}"
                if i < len(project.scenes) - 1:
                    vf += f",fade=t=out:st={max(0.0, duration-transition):.3f}:d={transition:.3f}"
            cmd = [
                ffmpeg, "-y",
                "-loop", "1", "-framerate", "30", "-t", f"{duration:.3f}",
                "-i", str(Path(scene.image_path).resolve()),
                "-vf", vf,
                "-r", "30", "-an",
                "-c:v", "libx264", "-preset", "veryfast", "-crf", "20",
                "-pix_fmt", "yuv420p", "-movflags", "+faststart",
                str(target.resolve()),
            ]
            proc = subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
            if proc.returncode != 0:
                raise RuntimeError(
                    f"FFmpeg could not prepare scene {scene.index}:\n"
                    + proc.stderr.decode("utf-8", errors="replace")[-1800:]
                )
            clips.append(target)
        return clips

    def _combine_filter(
        self,
        project: Project,
        transitions: bool,
        burn_captions: bool,
    ) -> tuple[str, str]:
        filters: list[str] = []
        labels: list[str] = []
        for i in range(len(project.scenes)):
            filters.append(f"[{i}:v]fps=30,setpts=PTS-STARTPTS,format=yuv420p[v{i}]")
            labels.append(f"[v{i}]")
        current = "[joined]"
        filters.append(f"{''.join(labels)}concat=n={len(labels)}:v=1:a=0{current}")
        if burn_captions:
            filters.append(f"{current}{self._caption_filter()}[vout]")
            current = "[vout]"
        return ";".join(filters), current

    def render(
        self,
        project: Project,
        audio: Path,
        captions: Path | None,
        out_dir: Path,
        motion: bool = True,
        transitions: bool = True,
    ) -> tuple[Path, bool]:
        if not project.scenes:
            raise RuntimeError("Project has no scenes to render")
        ffmpeg = self._ffmpeg()
        output = out_dir / "final.mp4"
        clips = self._render_scene_clips(project, out_dir, motion, transitions)

        def run(burn_captions: bool) -> subprocess.CompletedProcess:
            cmd: list[str] = [ffmpeg, "-y"]
            for clip in clips:
                cmd += ["-i", str(clip.resolve())]
            audio_index = len(clips)
            cmd += ["-i", str(audio.resolve())]
            graph, video_label = self._combine_filter(project, transitions, burn_captions)
            cmd += [
                "-filter_complex", graph,
                "-map", video_label,
                "-map", f"{audio_index}:a:0",
                "-c:v", "libx264", "-preset", "veryfast", "-crf", "20", "-pix_fmt", "yuv420p",
                "-c:a", "aac", "-b:a", "128k", "-shortest", "-movflags", "+faststart",
                str(output.resolve()),
            ]
            return subprocess.run(cmd, cwd=str(out_dir), stdout=subprocess.PIPE, stderr=subprocess.PIPE)

        want_captions = bool(captions and captions.exists())
        proc = run(want_captions)
        burned = want_captions
        if proc.returncode != 0 and want_captions:
            proc = run(False)
            burned = False
        if proc.returncode != 0:
            raise RuntimeError(
                "FFmpeg render failed:\n" + proc.stderr.decode("utf-8", errors="replace")[-2400:]
            )

        for clip in clips:
            try:
                clip.unlink()
            except OSError:
                pass
        return output, burned

def diagnostics(settings: Settings) -> list[tuple[str, bool, str]]:
    rows: list[tuple[str, bool, str]] = []

    try:
        tags = _get_json(settings.ollama_url.rstrip("/") + "/api/tags", timeout=2)
        names = [m.get("name", "") for m in tags.get("models", [])]
        model_ok = any(name == settings.ollama_model or name.startswith(settings.ollama_model + ":") for name in names)
        rows.append(("Ollama", True, settings.ollama_url))
        rows.append(("Script model", model_ok, settings.ollama_model + (" (ready)" if model_ok else " (not pulled)")))
    except Exception:
        rows.append(("Ollama", False, settings.ollama_url + " (offline)"))
        rows.append(("Script model", False, settings.ollama_model + " (unknown)"))

    try:
        info = _get_json(settings.comfy_url.rstrip("/") + "/object_info", timeout=3)
        rows.append(("ComfyUI", True, settings.comfy_url))
        node_ok = "Flux2Scheduler" in info and "EmptyFlux2LatentImage" in info
        rows.append(("FLUX.2 nodes", node_ok, "ready" if node_ok else "Update ComfyUI"))
        for label, node, field, name in [
            ("FLUX.2 model", "UNETLoader", "unet_name", settings.comfy_unet),
            ("FLUX.2 text encoder", "CLIPLoader", "clip_name", settings.comfy_clip),
            ("FLUX.2 VAE", "VAELoader", "vae_name", settings.comfy_vae),
        ]:
            try:
                available = info[node]["input"]["required"][field][0]
                ok = name in available
            except Exception:
                ok = False
            rows.append((label, ok, name))
    except Exception:
        rows.append(("ComfyUI", False, settings.comfy_url + " (offline)"))
        rows.extend([
            ("FLUX.2 nodes", False, "unknown"),
            ("FLUX.2 model", False, settings.comfy_unet),
            ("FLUX.2 text encoder", False, settings.comfy_clip),
            ("FLUX.2 VAE", False, settings.comfy_vae),
        ])

    try:
        import kokoro_onnx  # noqa: F401
        import soundfile  # noqa: F401
        kokoro_ok = True
    except Exception:
        kokoro_ok = False
    model_path = Path(settings.kokoro_model_path).expanduser()
    voices_path = Path(settings.kokoro_voices_path).expanduser()
    rows.append(("Kokoro", kokoro_ok, "installed" if kokoro_ok else "kokoro-onnx missing"))
    rows.append(("Voice model", model_path.exists() and model_path.stat().st_size > 1_000_000 if model_path.exists() else False, model_path.name))
    rows.append(("Voice pack", voices_path.exists() and voices_path.stat().st_size > 1_000_000 if voices_path.exists() else False, voices_path.name))

    ffmpeg = find_executable(settings.ffmpeg_exe, "ffmpeg")
    if not ffmpeg:
        try:
            import imageio_ffmpeg
            ffmpeg = imageio_ffmpeg.get_ffmpeg_exe()
        except Exception:
            ffmpeg = None
    rows.append(("FFmpeg", bool(ffmpeg), ffmpeg or "Not found"))
    return rows
