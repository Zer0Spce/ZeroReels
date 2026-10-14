from __future__ import annotations

from pathlib import Path
import json
import math
import re
import subprocess

from .models import Scene
from . import services


def _human_script_generate(self, project, scene_count: int):
    target_words = max(45, round(project.target_seconds * 2.35))
    words_per_scene = max(8, round(target_words / max(1, scene_count)))
    schema = {
        "type": "object",
        "properties": {
            "title": {"type": "string"},
            "script": {"type": "string"},
            "visual_anchor": {"type": "string"},
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
        "required": ["title", "script", "visual_anchor", "scenes"],
    }
    prompt = f"""You are the senior script editor and visual director for a polished human-made short video.

TOPIC: {project.topic}
VISUAL STYLE: {project.style}
TARGET LENGTH: about {project.target_seconds} seconds / about {target_words} spoken words
SCENES: exactly {scene_count}, roughly {words_per_scene} spoken words per scene

Write for a real narrator, not for an AI demo.

NARRATION RULES
- Hook immediately with a specific, natural opening. No generic 'Imagine this', 'Did you know', 'In a world', or fake hype.
- Use natural contractions where appropriate and vary sentence length and rhythm.
- Prefer concrete nouns and active verbs. Remove filler, repetition, throat-clearing, and generic transitions.
- Each scene should sound like the next thought in one continuous story, not a numbered list.
- Use punctuation deliberately so a voice actor naturally pauses and emphasizes the right ideas.
- Avoid repetitive patterns such as 'But here's the thing', 'What happened next', 'As time passed', and 'This changed everything'.
- Do not say 'Scene', 'in this video', or mention the production process.
- The final scene should land cleanly and feel finished. Do not add a generic subscribe/follow CTA.
- For factual topics, never invent quotes, statistics, document text, dates, official findings, or events just to sound specific. If uncertain, phrase cautiously instead of fabricating detail.

VISUAL CONTINUITY RULES
- Create one concise visual_anchor defining the recurring palette, lighting, texture, era, lens language, and subject continuity.
- Every image_prompt must describe a distinct shot while preserving that visual_anchor.
- Vary framing naturally: establishing, medium, detail, overhead, silhouette, environmental, etc. Do not repeat the same composition.
- Do not request readable words, captions, signs, labels, logos, watermarks, interfaces, newspapers, official documents, or legible screens.
- If the idea involves records/documents/screens, show them only as abstract/unreadable background detail; never fabricate convincing document text.
- Do not put subtitles or typography inside generated images.
- Favor believable human anatomy, realistic object scale, coherent perspective, and a clear visual subject.

Return only data matching the JSON schema."""
    endpoint = self.settings.ollama_url.rstrip("/") + "/api/generate"
    result = services._post_json(
        endpoint,
        {
            "model": self.settings.ollama_model,
            "prompt": prompt,
            "stream": False,
            "format": schema,
            "think": False,
            "options": {"temperature": 0.38, "top_p": 0.9},
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

    visual_anchor = " ".join(str(data.get("visual_anchor", "")).split()).strip()
    if not visual_anchor:
        visual_anchor = f"{project.style}, cohesive lighting and lens language, consistent visual identity"

    provisional = max(2.0, project.target_seconds / scene_count)
    scenes_out: list[Scene] = []
    for i, item in enumerate(raw_scenes):
        narration = " ".join(str(item.get("narration", "")).split()).strip()
        raw_prompt = " ".join(str(item.get("image_prompt", "")).split()).strip()
        prompt_text = (
            f"{visual_anchor}. {raw_prompt}. "
            "clean cinematic frame, believable anatomy and perspective, no readable text, no letters, "
            "no signage, no logos, no watermarks, no UI, no legible documents, no subtitles"
        )
        scenes_out.append(Scene(i + 1, narration, prompt_text, provisional))

    if any(not scene.narration or not scene.image_prompt for scene in scenes_out):
        raise RuntimeError("Ollama returned an incomplete scene")

    # A short second pass line-edits narration only. It is explicitly forbidden from adding facts.
    polish_schema = {
        "type": "object",
        "properties": {
            "scenes": {
                "type": "array",
                "minItems": scene_count,
                "maxItems": scene_count,
                "items": {
                    "type": "object",
                    "properties": {"narration": {"type": "string"}},
                    "required": ["narration"],
                },
            }
        },
        "required": ["scenes"],
    }
    draft = "\n".join(f"{i + 1}. {s.narration}" for i, s in enumerate(scenes_out))
    polish_prompt = f"""Line-edit this narration so it sounds spoken by a skilled human narrator.
Do NOT add any new facts, names, dates, numbers, claims, or events. Preserve meaning.
Keep exactly {scene_count} scenes and approximately the same total length.
Improve rhythm, contractions, punctuation, sentence variety, and transitions between thoughts.
Remove robotic phrasing, repeated sentence structures, filler, and unnecessary adjectives.
Keep the hook strong and the ending restrained and satisfying.

DRAFT:\n{draft}

Return only the required JSON."""
    try:
        polished = services._post_json(
            endpoint,
            {
                "model": self.settings.ollama_model,
                "prompt": polish_prompt,
                "stream": False,
                "format": polish_schema,
                "think": False,
                "options": {"temperature": 0.22, "top_p": 0.85},
            },
            timeout=600,
        )
        pdata = json.loads(polished["response"])
        pscenes = pdata.get("scenes", [])
        if len(pscenes) == scene_count:
            for scene, item in zip(scenes_out, pscenes):
                value = " ".join(str(item.get("narration", "")).split()).strip()
                if value:
                    scene.narration = value
    except Exception:
        # The first pass is already valid; polishing is an enhancement, not a blocker.
        pass

    project.title = str(data.get("title") or project.topic).strip()[:100]
    script = " ".join(scene.narration for scene in scenes_out).strip()
    return script, scenes_out


def _pause_after(text: str, index: int, total: int) -> float:
    t = text.rstrip()
    if index == total - 1:
        return 0.0
    if t.endswith(("?", "!")):
        return 0.24
    if t.endswith((".", "…")):
        return 0.20
    if t.endswith((";", ":")):
        return 0.16
    return 0.14


def _human_voice_generate(self, project, out_dir: Path, progress=None) -> Path:
    model_path = Path(self.settings.kokoro_model_path).expanduser()
    voices_path = Path(self.settings.kokoro_voices_path).expanduser()
    if not model_path.exists() or not voices_path.exists():
        raise RuntimeError("Kokoro voice files are missing. Open Setup and download the local voice model first.")

    try:
        import soundfile as sf
        from kokoro_onnx import Kokoro
    except Exception as exc:
        raise RuntimeError("Kokoro voice engine is not installed correctly. Run setup.bat again.") from exc

    kokoro = Kokoro(str(model_path), str(voices_path))
    parts: list[Path] = []
    pauses: list[float] = []
    total = len(project.scenes)
    base_speed = float(self.settings.kokoro_speed)

    for i, scene in enumerate(project.scenes):
        if progress:
            progress(64 + int(8 * i / max(1, total)), f"Voice-over scene {i + 1} of {total}")
        path = out_dir / f"voice_{scene.index:03d}.wav"
        # Tiny scene-to-scene variation avoids a metronomic delivery without changing character.
        shape = (-0.012 if i == 0 else (0.010 if i % 3 == 1 else (-0.006 if i % 3 == 2 else 0.0)))
        speed = max(0.82, min(1.18, base_speed * (1.0 + shape)))
        try:
            samples, sample_rate = kokoro.create(
                scene.narration,
                voice=self.settings.kokoro_voice,
                speed=speed,
                lang=self.settings.kokoro_lang,
            )
            sf.write(str(path), samples, sample_rate, subtype="PCM_16")
        except Exception as exc:
            raise RuntimeError("Kokoro voice-over failed. Check the selected voice and local model files.\n" + str(exc)) from exc
        if not path.exists() or path.stat().st_size < 1000:
            raise RuntimeError("Kokoro did not create a valid narration WAV file")
        pause = _pause_after(scene.narration, i, total)
        scene.audio_path = str(path)
        scene.duration = max(1.0, services._wav_duration(path) + pause)
        parts.append(path)
        pauses.append(pause)

    target = out_dir / "narration.wav"
    if not parts:
        raise RuntimeError("No narration audio was generated")

    # Concatenate with punctuation-aware silence instead of one identical gap everywhere.
    import wave
    with wave.open(str(parts[0]), "rb") as first:
        params = first.getparams()
    with wave.open(str(target), "wb") as out:
        out.setparams(params)
        for index, part in enumerate(parts):
            with wave.open(str(part), "rb") as src:
                if (src.getnchannels(), src.getsampwidth(), src.getframerate()) != (params.nchannels, params.sampwidth, params.framerate):
                    raise RuntimeError("Voice engine produced inconsistent WAV formats")
                out.writeframes(src.readframes(src.getnframes()))
            if pauses[index] > 0:
                frames = int(params.framerate * pauses[index])
                out.writeframes(b"\x00" * frames * params.nchannels * params.sampwidth)
    return target


def _caption_groups(text: str) -> list[list[str]]:
    words = " ".join(text.split()).split()
    groups: list[list[str]] = []
    current: list[str] = []
    for word in words:
        current.append(word)
        clean_len = len(" ".join(current))
        strong_break = bool(re.search(r"[.!?…][\"')\]]?$", word))
        soft_break = bool(re.search(r"[,;:][\"')\]]?$", word))
        if (strong_break and len(current) >= 2) or (soft_break and len(current) >= 3) or len(current) >= 6 or clean_len >= 34:
            groups.append(current)
            current = []
    if current:
        if groups and len(current) == 1 and len(groups[-1]) <= 4:
            groups[-1].extend(current)
        else:
            groups.append(current)
    return groups


def _caption_text(words: list[str]) -> str:
    text = " ".join(words)
    if len(text) <= 24 or len(words) <= 3:
        return text
    midpoint = len(text) / 2
    best = None
    cursor = 0
    for i in range(1, len(words)):
        cursor += len(words[i - 1]) + 1
        score = abs(cursor - midpoint)
        if best is None or score < best[0]:
            best = (score, i)
    if best:
        i = best[1]
        return " ".join(words[:i]) + "\n" + " ".join(words[i:])
    return text


def _human_captions(self, project, out_dir: Path) -> Path:
    path = out_dir / "captions.srt"
    cursor = 0.0
    entries: list[str] = []
    caption_index = 1
    for scene in project.scenes:
        groups = _caption_groups(scene.narration)
        if not groups:
            cursor += scene.duration
            continue
        weights = [max(2.0, sum(len(w.strip(".,!?;:\"'")) for w in group) / 4.5) for group in groups]
        total_weight = sum(weights)
        used = 0.0
        for idx, (group, weight) in enumerate(zip(groups, weights)):
            duration = scene.duration * weight / total_weight
            # Keep captions readable but never push them outside the scene.
            remaining = scene.duration - used
            duration = min(remaining, max(0.50, duration))
            start = cursor + used
            end = min(cursor + scene.duration, start + duration)
            if idx == len(groups) - 1:
                end = cursor + scene.duration
            entries.append(
                f"{caption_index}\n{self._stamp(start)} --> {self._stamp(end)}\n{_caption_text(group)}\n"
            )
            caption_index += 1
            used = end - cursor
        cursor += scene.duration
    path.write_text("\n".join(entries), encoding="utf-8")
    return path


def _caption_filter() -> str:
    style = (
        "FontName=Segoe UI Semibold,FontSize=19,Bold=1,PrimaryColour=&H00FFFFFF,"
        "OutlineColour=&HCC000000,BorderStyle=1,Outline=2.2,Shadow=0,"
        "Alignment=2,MarginL=70,MarginR=70,MarginV=125,Spacing=0.2"
    )
    return f"subtitles=captions.srt:force_style='{style}'"


def _scene_filter(self, scene_index: int, width: int, height: int, frames: int, motion: bool) -> str:
    base = (
        f"scale={width}:{height}:force_original_aspect_ratio=increase,crop={width}:{height},"
        "eq=contrast=1.025:saturation=1.035:brightness=-0.003,unsharp=5:5:0.18:5:5:0.0"
    )
    if not motion:
        return base + ",fps=30,format=yuv420p"

    f = max(1, frames)
    patterns = [
        "z='min(zoom+0.00045,1.055)':x='iw/2-(iw/zoom/2)':y='ih/2-(ih/zoom/2)'",
        f"z='1.045':x='(iw-iw/zoom)*on/{f}':y='ih/2-(ih/zoom/2)'",
        f"z='1.045':x='(iw-iw/zoom)*(1-on/{f})':y='ih/2-(ih/zoom/2)'",
        f"z='1.04':x='iw/2-(iw/zoom/2)':y='(ih-ih/zoom)*on/{f}'",
        f"z='1.04':x='iw/2-(iw/zoom/2)':y='(ih-ih/zoom)*(1-on/{f})'",
        "z='max(1.0,1.055-on*0.00040)':x='iw/2-(iw/zoom/2)':y='ih/2-(ih/zoom/2)'",
    ]
    zp = patterns[scene_index % len(patterns)]
    return base + f",zoompan={zp}:d=1:s={width}x{height}:fps=30,format=yuv420p"


def _render_scene_clips(self, project, out_dir: Path, motion: bool, transitions: bool):
    ffmpeg = self._ffmpeg()
    width, height = services.dimensions_for(project.format)
    transition = max(0.08, min(float(self.settings.transition_seconds), 0.55)) if transitions else 0.0
    clips: list[Path] = []
    for i, scene in enumerate(project.scenes):
        base_duration = max(0.25, scene.duration)
        # Extra tail is consumed by xfade, so the final timeline still matches narration exactly.
        duration = base_duration + (transition if transitions and i < len(project.scenes) - 1 else 0.0)
        frames = max(1, int(round(duration * 30)))
        target = out_dir / f"_clip_{scene.index:03d}.mp4"
        vf = self._scene_filter(i, width, height, frames, motion)
        cmd = [
            ffmpeg, "-y", "-loop", "1", "-framerate", "30", "-t", f"{duration:.3f}",
            "-i", str(Path(scene.image_path).resolve()), "-vf", vf, "-r", "30", "-an",
            "-c:v", "libx264", "-preset", "veryfast", "-crf", "19",
            "-pix_fmt", "yuv420p", "-movflags", "+faststart", str(target.resolve()),
        ]
        proc = subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
        if proc.returncode != 0:
            raise RuntimeError(f"FFmpeg could not prepare scene {scene.index}:\n" + proc.stderr.decode("utf-8", errors="replace")[-1800:])
        clips.append(target)
    return clips


def _combine_filter(self, project, transitions: bool, burn_captions: bool):
    filters: list[str] = []
    n = len(project.scenes)
    for i in range(n):
        filters.append(f"[{i}:v]fps=30,setpts=PTS-STARTPTS,format=yuv420p[v{i}]")

    if transitions and n > 1:
        t = max(0.08, min(float(self.settings.transition_seconds), 0.55))
        current = "[v0]"
        offset = 0.0
        for i in range(1, n):
            offset += max(0.25, project.scenes[i - 1].duration)
            out = f"[x{i}]"
            filters.append(f"{current}[v{i}]xfade=transition=fade:duration={t:.3f}:offset={offset:.3f}{out}")
            current = out
    else:
        labels = "".join(f"[v{i}]" for i in range(n))
        current = "[joined]"
        filters.append(f"{labels}concat=n={n}:v=1:a=0{current}")

    if burn_captions:
        filters.append(f"{current}{self._caption_filter()}[vout]")
        current = "[vout]"
    return ";".join(filters), current


def _render(self, project, audio: Path, captions: Path | None, out_dir: Path, motion=True, transitions=True):
    if not project.scenes:
        raise RuntimeError("Project has no scenes to render")
    ffmpeg = self._ffmpeg()
    output = out_dir / "final.mp4"
    clips = self._render_scene_clips(project, out_dir, motion, transitions)

    def run(burn_captions: bool):
        cmd: list[str] = [ffmpeg, "-y"]
        for clip in clips:
            cmd += ["-i", str(clip.resolve())]
        audio_index = len(clips)
        cmd += ["-i", str(audio.resolve())]
        graph, video_label = self._combine_filter(project, transitions, burn_captions)
        graph += f";[{audio_index}:a]highpass=f=65,loudnorm=I=-16:TP=-1.5:LRA=8[aout]"
        cmd += [
            "-filter_complex", graph,
            "-map", video_label, "-map", "[aout]",
            "-c:v", "libx264", "-preset", "veryfast", "-crf", "19", "-pix_fmt", "yuv420p",
            "-c:a", "aac", "-b:a", "160k", "-shortest", "-movflags", "+faststart", str(output.resolve()),
        ]
        return subprocess.run(cmd, cwd=str(out_dir), stdout=subprocess.PIPE, stderr=subprocess.PIPE)

    want_captions = bool(captions and captions.exists())
    proc = run(want_captions)
    burned = want_captions
    if proc.returncode != 0 and want_captions:
        proc = run(False)
        burned = False
    if proc.returncode != 0:
        raise RuntimeError("FFmpeg render failed:\n" + proc.stderr.decode("utf-8", errors="replace")[-2600:])

    for clip in clips:
        try:
            clip.unlink()
        except OSError:
            pass
    return output, burned


def install() -> None:
    services.ScriptService.generate = _human_script_generate
    services.KokoroVoiceService.generate = _human_voice_generate
    services.CaptionService.generate_from_scenes = _human_captions
    services.FFmpegRenderer._caption_filter = staticmethod(_caption_filter)
    services.FFmpegRenderer._scene_filter = _scene_filter
    services.FFmpegRenderer._render_scene_clips = _render_scene_clips
    services.FFmpegRenderer._combine_filter = _combine_filter
    services.FFmpegRenderer.render = _render
