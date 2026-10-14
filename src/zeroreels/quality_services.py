from __future__ import annotations

from pathlib import Path
import hashlib
import json
import random
import re
import subprocess

from .models import Scene
from . import services


def _continuity_instruction(mode: str) -> str:
    if mode == "Same Cast & World":
        return (
            "Lock recurring people and locations very strongly. Give recurring people exact stable physical traits, age range, "
            "hair, clothing, and silhouette in continuity_bible, and repeat those traits in every relevant image prompt. "
            "Treat the sequence like shots from one production with the same cast, props, architecture, era, and world."
        )
    if mode == "Independent Shots":
        return (
            "Each scene may use a fresh subject or setting when it improves storytelling. Keep only the overall visual style, era, "
            "palette, and photographic language coherent. Do not force the same person into unrelated scenes."
        )
    return (
        "Preserve recurring people, locations, props, era, palette, and wardrobe whenever they reappear, while allowing the camera "
        "and setting to change naturally as the story advances. continuity_bible should contain concrete recurring traits."
    )


def _human_script_generate(self, project, scene_count: int):
    target_words = max(45, round(project.target_seconds * 2.35))
    words_per_scene = max(8, round(target_words / max(1, scene_count)))
    continuity_mode = getattr(project, "continuity_mode", "Consistent Story")
    continuity_rule = _continuity_instruction(continuity_mode)
    schema = {
        "type": "object",
        "properties": {
            "title": {"type": "string"},
            "script": {"type": "string"},
            "visual_anchor": {"type": "string"},
            "continuity_bible": {"type": "string"},
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
        "required": ["title", "script", "visual_anchor", "continuity_bible", "scenes"],
    }
    prompt = f"""You are the senior script editor and visual director for a polished human-made short video.

TOPIC: {project.topic}
VISUAL STYLE: {project.style}
VISUAL CONTINUITY MODE: {continuity_mode}
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

VISUAL DIRECTION RULES
- Create visual_anchor defining palette, lighting, texture, era, lens language, and overall production design.
- Create continuity_bible defining recurring people, locations, props, vehicles, wardrobe, architecture, or other stable story elements. If no person recurs, lock the important place/object/world instead.
- Continuity instruction: {continuity_rule}
- Every image_prompt must be one distinct shot and must obey visual_anchor plus continuity_bible where relevant.
- Vary framing naturally: establishing, medium, close detail, overhead, silhouette, environmental, etc. Do not repeat the same composition.
- Never request readable words, captions, signs, labels, logos, watermarks, interfaces, newspapers, official documents, or legible screens.
- If records/documents/screens are visually useful, make all writing abstract, blurred, turned away, cropped, or illegible. Never fabricate convincing document text.
- Do not put subtitles or typography inside generated images.
- Favor believable human anatomy, realistic object scale, coherent perspective, natural hands, and one clear visual subject.

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
    continuity_bible = " ".join(str(data.get("continuity_bible", "")).split()).strip()
    if not visual_anchor:
        visual_anchor = f"{project.style}, cohesive lighting and lens language, consistent visual identity"
    if not continuity_bible:
        continuity_bible = "preserve recurring subjects, wardrobe, locations, props, era, and physical traits across related shots"

    seed_material = f"{project.topic}|{project.style}|{visual_anchor}|{continuity_bible}".encode("utf-8")
    base_seed = int(hashlib.sha256(seed_material).hexdigest()[:8], 16) % 2_147_483_647
    provisional = max(2.0, project.target_seconds / scene_count)
    scenes_out: list[Scene] = []
    for i, item in enumerate(raw_scenes):
        narration = " ".join(str(item.get("narration", "")).split()).strip()
        raw_prompt = " ".join(str(item.get("image_prompt", "")).split()).strip()
        bible = "" if continuity_mode == "Independent Shots" else f" Continuity bible: {continuity_bible}."
        if continuity_mode == "Same Cast & World":
            seed_marker = f" [ZR-SEED={base_seed}]"
        elif continuity_mode == "Consistent Story":
            seed_marker = f" [ZR-SEED={(base_seed + i * 7919) % 2_147_483_647}]"
        else:
            seed_marker = ""
        prompt_text = (
            f"{visual_anchor}.{bible} Shot {i + 1}: {raw_prompt}. "
            "clean cinematic frame, natural human proportions, believable hands, coherent perspective, realistic scale, "
            "no readable text, no letters, no signage, no logos, no watermarks, no UI, no legible documents, no subtitles"
            + seed_marker
        )
        scenes_out.append(Scene(i + 1, narration, prompt_text, provisional))

    if any(not scene.narration or not scene.image_prompt for scene in scenes_out):
        raise RuntimeError("Ollama returned an incomplete scene")

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
        pass

    project.title = str(data.get("title") or project.topic).strip()[:100]
    script = " ".join(scene.narration for scene in scenes_out).strip()
    return script, scenes_out


def _quality_workflow(self, prompt: str, fmt: str) -> dict:
    width, height = services.generation_dimensions_for(fmt)
    match = re.search(r"\s*\[ZR-SEED=(\d+)\]\s*$", prompt)
    if match:
        seed = max(1, int(match.group(1)))
        clean_prompt = prompt[:match.start()].rstrip()
    else:
        seed = random.randint(1, 2_147_483_647)
        clean_prompt = prompt
    s = self.settings
    return {
        "1": {"class_type": "UNETLoader", "inputs": {"unet_name": s.comfy_unet, "weight_dtype": "default"}},
        "2": {"class_type": "CLIPLoader", "inputs": {"clip_name": s.comfy_clip, "type": "flux2", "device": "default"}},
        "3": {"class_type": "VAELoader", "inputs": {"vae_name": s.comfy_vae}},
        "4": {"class_type": "CLIPTextEncode", "inputs": {"text": clean_prompt, "clip": ["2", 0]}},
        "5": {"class_type": "ConditioningZeroOut", "inputs": {"conditioning": ["4", 0]}},
        "6": {"class_type": "CFGGuider", "inputs": {"model": ["1", 0], "positive": ["4", 0], "negative": ["5", 0], "cfg": 1.0}},
        "7": {"class_type": "RandomNoise", "inputs": {"noise_seed": seed}},
        "8": {"class_type": "KSamplerSelect", "inputs": {"sampler_name": "euler"}},
        "9": {"class_type": "Flux2Scheduler", "inputs": {"steps": 4, "width": width, "height": height}},
        "10": {"class_type": "EmptyFlux2LatentImage", "inputs": {"width": width, "height": height, "batch_size": 1}},
        "11": {"class_type": "SamplerCustomAdvanced", "inputs": {"noise": ["7", 0], "guider": ["6", 0], "sampler": ["8", 0], "sigmas": ["9", 0], "latent_image": ["10", 0]}},
        "12": {"class_type": "VAEDecode", "inputs": {"samples": ["11", 0], "vae": ["3", 0]}},
        "13": {"class_type": "SaveImage", "inputs": {"filename_prefix": "ZeroReels", "images": ["12", 0]}},
    }


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
        shape = (-0.012 if i == 0 else (0.010 if i % 3 == 1 else (-0.006 if i % 3 == 2 else 0.0)))
        speed = max(0.82, min(1.18, base_speed * (1.0 + shape)))
        try:
            samples, sample_rate = kokoro.create(scene.narration, voice=self.settings.kokoro_voice, speed=speed, lang=self.settings.kokoro_lang)
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
            remaining = scene.duration - used
            duration = min(remaining, max(0.50, duration))
            start = cursor + used
            end = min(cursor + scene.duration, start + duration)
            if idx == len(groups) - 1:
                end = cursor + scene.duration
            entries.append(f"{caption_index}\n{self._stamp(start)} --> {self._stamp(end)}\n{_caption_text(group)}\n")
            caption_index += 1
            used = end - cursor
        cursor += scene.duration
    path.write_text("\n".join(entries), encoding="utf-8")
    return path


def _caption_filter(self) -> str:
    position = getattr(self, "_zr_caption_position", "Bottom")
    size_name = getattr(self, "_zr_caption_size", "Small")
    font_size = {"Small": 15, "Medium": 18, "Large": 21}.get(size_name, 15)
    margin = {"Bottom": 48, "Safe Lower": 105, "Center-Lower": 260}.get(position, 48)
    style = (
        f"FontName=Segoe UI Semibold,FontSize={font_size},Bold=1,PrimaryColour=&H00FFFFFF,"
        "OutlineColour=&HCC000000,BorderStyle=1,Outline=2.0,Shadow=0,"
        f"Alignment=2,MarginL=68,MarginR=68,MarginV={margin},Spacing=0.1"
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


def _transition_config(self, transitions: bool) -> tuple[bool, str, float]:
    if not transitions:
        return False, "fade", 0.0
    style = getattr(self, "_zr_transition_style", "Natural Crossfade")
    if style == "Clean Cut":
        return False, "fade", 0.0
    transition_name = {
        "Natural Crossfade": "fade",
        "Soft Dissolve": "dissolve",
        "Smooth Push": "smoothleft",
    }.get(style, "fade")
    base = max(0.08, min(float(self.settings.transition_seconds), 0.55))
    if style == "Natural Crossfade":
        base = min(base, 0.32)
    elif style == "Smooth Push":
        base = min(base, 0.26)
    return True, transition_name, base


def _render_scene_clips(self, project, out_dir: Path, motion: bool, transitions: bool):
    ffmpeg = self._ffmpeg()
    width, height = services.dimensions_for(project.format)
    use_xfade, _name, transition = self._transition_config(transitions)
    clips: list[Path] = []
    for i, scene in enumerate(project.scenes):
        base_duration = max(0.25, scene.duration)
        duration = base_duration + (transition if use_xfade and i < len(project.scenes) - 1 else 0.0)
        frames = max(1, int(round(duration * 30)))
        target = out_dir / f"_clip_{scene.index:03d}.mp4"
        vf = self._scene_filter(i, width, height, frames, motion)
        cmd = [
            ffmpeg, "-y", "-loop", "1", "-framerate", "30", "-t", f"{duration:.3f}",
            "-i", str(Path(scene.image_path).resolve()), "-vf", vf, "-r", "30", "-an",
            "-c:v", "libx264", "-preset", "veryfast", "-crf", "19", "-pix_fmt", "yuv420p",
            "-movflags", "+faststart", str(target.resolve()),
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

    use_xfade, transition_name, transition = self._transition_config(transitions)
    if use_xfade and n > 1:
        current = "[v0]"
        offset = 0.0
        for i in range(1, n):
            offset += max(0.25, project.scenes[i - 1].duration)
            out = f"[x{i}]"
            filters.append(
                f"{current}[v{i}]xfade=transition={transition_name}:duration={transition:.3f}:offset={offset:.3f}{out}"
            )
            current = out
    else:
        labels = "".join(f"[v{i}]" for i in range(n))
        current = "[joined]"
        filters.append(f"{labels}concat=n={n}:v=1:a=0{current}")

    if burn_captions:
        filters.append(f"{current}{self._caption_filter()}[vout]")
        current = "[vout]"
    return ";".join(filters), current


def _render(
    self,
    project,
    audio: Path,
    captions: Path | None,
    out_dir: Path,
    motion=True,
    transitions=True,
    caption_position="Bottom",
    caption_size="Small",
    transition_style="Natural Crossfade",
):
    if not project.scenes:
        raise RuntimeError("Project has no scenes to render")
    self._zr_caption_position = caption_position
    self._zr_caption_size = caption_size
    self._zr_transition_style = transition_style
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
        graph += f";[{audio_index}:a]highpass=f=65,acompressor=threshold=-18dB:ratio=2.2:attack=20:release=180,loudnorm=I=-16:TP=-1.5:LRA=8[aout]"
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
    services.ComfyImageService._workflow = _quality_workflow
    services.KokoroVoiceService.generate = _human_voice_generate
    services.CaptionService.generate_from_scenes = _human_captions
    services.FFmpegRenderer._caption_filter = _caption_filter
    services.FFmpegRenderer._scene_filter = _scene_filter
    services.FFmpegRenderer._transition_config = _transition_config
    services.FFmpegRenderer._render_scene_clips = _render_scene_clips
    services.FFmpegRenderer._combine_filter = _combine_filter
    services.FFmpegRenderer.render = _render
