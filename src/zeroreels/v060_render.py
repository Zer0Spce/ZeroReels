from __future__ import annotations

from pathlib import Path
import hashlib
import re
import subprocess

from . import services
from .models import Project
from .v060_story import keyword_for_phrase


AUDIO_EXTENSIONS = {".mp3", ".wav", ".m4a", ".aac", ".flac", ".ogg"}


def _ass_time(seconds: float) -> str:
    cs = max(0, int(round(seconds * 100)))
    h, cs = divmod(cs, 360000)
    m, cs = divmod(cs, 6000)
    s, cs = divmod(cs, 100)
    return f"{h}:{m:02d}:{s:02d}.{cs:02d}"


def _caption_groups(text: str, max_words: int = 5) -> list[list[str]]:
    words = " ".join((text or "").split()).split()
    groups: list[list[str]] = []
    current: list[str] = []
    for word in words:
        current.append(word)
        strong = bool(re.search(r"[.!?…][\"')\]]?$", word))
        soft = bool(re.search(r"[,;:][\"')\]]?$", word))
        if (strong and len(current) >= 2) or (soft and len(current) >= 3) or len(current) >= max_words:
            groups.append(current)
            current = []
    if current:
        if groups and len(current) == 1 and len(groups[-1]) < max_words:
            groups[-1].extend(current)
        else:
            groups.append(current)
    return groups


def _escape_ass(text: str) -> str:
    return text.replace("{", "(").replace("}", ")").replace("\n", " ")


def _highlight_keyword(text: str, enabled: bool) -> str:
    clean = _escape_ass(text)
    if not enabled:
        return clean
    keyword = keyword_for_phrase(clean)
    if not keyword:
        return clean
    match = re.search(rf"\b{re.escape(keyword)}\b", clean, flags=re.IGNORECASE)
    if not match:
        return clean
    yellow = r"{\1c&H0045C9F6&}"
    white = r"{\1c&H00FFFFFF&}"
    return clean[:match.start()] + yellow + clean[match.start():match.end()] + white + clean[match.end():]


def professional_captions(self, project: Project, out_dir: Path) -> Path:
    style_name = getattr(self, "_zr_caption_style", "TikTok Pop")
    position = getattr(self, "_zr_caption_position", "Bottom")
    size_name = getattr(self, "_zr_caption_size", "Small")
    width, height = services.dimensions_for(project.format)

    base_size = {
        "TikTok Pop": {"Small": 50, "Medium": 58, "Large": 66},
        "Clean Lower Third": {"Small": 42, "Medium": 50, "Large": 58},
        "Documentary": {"Small": 38, "Medium": 46, "Large": 54},
    }.get(style_name, {"Small": 46, "Medium": 54, "Large": 62})[size_name]
    if project.format == "16:9":
        base_size = int(base_size * 0.78)
    elif project.format == "1:1":
        base_size = int(base_size * 0.88)

    margin = {"Bottom": 118, "Safe Lower": 190, "Center-Lower": int(height * 0.28)}.get(position, 118)
    outline = 4 if style_name == "TikTok Pop" else 3
    shadow = 1 if style_name == "TikTok Pop" else 0
    bold = -1 if style_name != "Documentary" else 0

    header = f"""[Script Info]
ScriptType: v4.00+
PlayResX: {width}
PlayResY: {height}
ScaledBorderAndShadow: yes
WrapStyle: 2

[V4+ Styles]
Format: Name,Fontname,Fontsize,PrimaryColour,SecondaryColour,OutlineColour,BackColour,Bold,Italic,Underline,StrikeOut,ScaleX,ScaleY,Spacing,Angle,BorderStyle,Outline,Shadow,Alignment,MarginL,MarginR,MarginV,Encoding
Style: ZeroReels,Segoe UI Semibold,{base_size},&H00FFFFFF,&H0045C9F6,&HCC000000,&H50000000,{bold},0,0,0,100,100,0,0,1,{outline},{shadow},2,70,70,{margin},1

[Events]
Format: Layer,Start,End,Style,Name,MarginL,MarginR,MarginV,Effect,Text
"""

    lines: list[str] = [header]
    cursor = 0.0
    for scene in project.scenes:
        groups = _caption_groups(scene.narration, 5 if style_name == "TikTok Pop" else 7)
        if not groups:
            cursor += scene.duration
            continue
        weights = [max(1, len(group)) for group in groups]
        total_weight = sum(weights)
        used = 0.0
        for idx, (group, weight) in enumerate(zip(groups, weights)):
            duration = scene.duration * weight / total_weight
            start = cursor + used
            end = cursor + scene.duration if idx == len(groups) - 1 else min(cursor + scene.duration, start + duration)
            phrase = " ".join(group)
            if style_name == "TikTok Pop":
                text = r"{\fscx94\fscy94\t(0,120,\fscx100\fscy100)}" + _highlight_keyword(phrase, True)
            elif style_name == "Clean Lower Third":
                text = _highlight_keyword(phrase, True)
            else:
                text = _highlight_keyword(phrase, False)
            lines.append(f"Dialogue: 0,{_ass_time(start)},{_ass_time(end)},ZeroReels,,0,0,0,,{text}\n")
            used = end - cursor
        cursor += scene.duration

    path = out_dir / "captions.ass"
    path.write_text("".join(lines), encoding="utf-8-sig")
    return path


def professional_caption_filter(self) -> str:
    filename = getattr(self, "_zr_caption_filename", "captions.ass") or "captions.ass"
    if filename.lower().endswith(".ass"):
        return f"subtitles={filename}"
    # Backward-compatible fallback for older projects.
    return "subtitles=captions.srt"


def _story_transition_plan(self, project: Project, transitions: bool) -> list[tuple[str, float, str]]:
    boundaries = max(0, len(project.scenes) - 1)
    if not transitions or boundaries == 0:
        return [("cut", 0.0, "Clean Cut") for _ in range(boundaries)]

    style = getattr(self, "_zr_transition_style", "Story Rhythm")
    base = max(0.08, min(float(self.settings.transition_seconds), 0.45))
    if style == "Clean Cut":
        return [("cut", 0.0, "Clean Cut") for _ in range(boundaries)]
    if style == "Natural Crossfade":
        return [("fade", min(base, 0.24), "Crossfade") for _ in range(boundaries)]
    if style == "Soft Dissolve":
        return [("dissolve", min(base, 0.30), "Dissolve") for _ in range(boundaries)]
    if style == "Smooth Push":
        return [("smoothleft", min(base, 0.22), "Smooth Push") for _ in range(boundaries)]

    # Story Rhythm deliberately uses mostly cuts. Transitions are punctuation, not decoration.
    project_style = project.style
    plan: list[tuple[str, float, str]] = []
    for i in range(boundaries):
        if project_style in {"TikTok Story", "Viral Explainer", "Fast Social"}:
            use = i in {2, 5, 8, 11}
            plan.append(("fade", 0.13, "Quick Crossfade") if use else ("cut", 0.0, "Clean Cut"))
        elif project_style in {"Dark Curiosity", "Dark Mystery"}:
            use = i % 2 == 1
            plan.append(("dissolve", 0.22, "Soft Dissolve") if use else ("cut", 0.0, "Clean Cut"))
        elif project_style in {"Mini Documentary", "Cinematic Documentary"}:
            use = i in {2, 5, 8, 11}
            plan.append(("fade", 0.18, "Documentary Crossfade") if use else ("cut", 0.0, "Clean Cut"))
        else:
            use = i % 3 == 2
            plan.append(("fade", 0.16, "Crossfade") if use else ("cut", 0.0, "Clean Cut"))
    return plan


def _motion_filter(scene, width: int, height: int, frames: int, motion: bool) -> str:
    grade = (
        f"scale={width}:{height}:force_original_aspect_ratio=increase,crop={width}:{height},"
        "eq=contrast=1.035:saturation=1.015:brightness=-0.002,"
        "unsharp=5:5:0.16:5:5:0.0,noise=alls=1.0:allf=t+u,vignette=PI/34"
    )
    if not motion:
        scene.motion_style = "Static"
        return grade + ",fps=30,format=yuv420p"

    f = max(1, frames)
    role = scene.shot_role or "Action"
    if role == "Hook":
        zp = "z='min(zoom+0.00062,1.055)':x='iw/2-(iw/zoom/2)':y='ih/2-(ih/zoom/2)'"
        scene.motion_style = "Hook push"
    elif role == "Establishing":
        zp = f"z='1.035':x='(iw-iw/zoom)*on/{f}':y='ih/2-(ih/zoom/2)'"
        scene.motion_style = "Wide pan"
    elif role == "Detail":
        zp = "z='min(zoom+0.00035,1.04)':x='iw/2-(iw/zoom/2)':y='ih/2-(ih/zoom/2)'"
        scene.motion_style = "Detail push"
    elif role == "Peak":
        zp = "z='max(1.0,1.055-on*0.00040)':x='iw/2-(iw/zoom/2)':y='ih/2-(ih/zoom/2)'"
        scene.motion_style = "Scale reveal"
    elif role == "Aftermath":
        zp = f"z='1.018':x='iw/2-(iw/zoom/2)':y='(ih-ih/zoom)*on/{f}'"
        scene.motion_style = "Quiet drift"
    elif role == "Landing":
        zp = "z='min(zoom+0.00020,1.025)':x='iw/2-(iw/zoom/2)':y='ih/2-(ih/zoom/2)'"
        scene.motion_style = "Slow landing"
    elif role == "Escalation":
        zp = f"z='1.04':x='(iw-iw/zoom)*(1-on/{f})':y='ih/2-(ih/zoom/2)'"
        scene.motion_style = "Reverse pan"
    else:
        zp = "z='min(zoom+0.00042,1.045)':x='iw/2-(iw/zoom/2)':y='ih/2-(ih/zoom/2)'"
        scene.motion_style = "Action push"
    return grade + f",zoompan={zp}:d=1:s={width}x{height}:fps=30,format=yuv420p"


def professional_render_scene_clips(self, project: Project, out_dir: Path, motion: bool, transitions: bool):
    ffmpeg = self._ffmpeg()
    width, height = services.dimensions_for(project.format)
    plan = _story_transition_plan(self, project, transitions)
    self._zr_transition_plan = plan
    clips: list[Path] = []
    callback = getattr(self, "_zr_progress", None)
    for i, scene in enumerate(project.scenes):
        extra = plan[i][1] if i < len(plan) and plan[i][0] != "cut" else 0.0
        duration = max(0.25, scene.duration + extra)
        frames = max(1, int(round(duration * 30)))
        target = out_dir / f"_clip_{scene.index:03d}.mp4"
        vf = _motion_filter(scene, width, height, frames, motion)
        if i < len(plan):
            scene.transition_to_next = plan[i][2]
        else:
            scene.transition_to_next = "End"
        if callback:
            callback(84 + int(6 * i / max(1, len(project.scenes))), f"Editing scene {i + 1}/{len(project.scenes)} • {scene.motion_style}")
        cmd = [
            ffmpeg, "-y", "-loop", "1", "-framerate", "30", "-t", f"{duration:.3f}",
            "-i", str(Path(scene.image_path).resolve()), "-vf", vf, "-r", "30", "-an",
            "-c:v", "libx264", "-preset", "veryfast", "-crf", "19", "-pix_fmt", "yuv420p",
            "-movflags", "+faststart", str(target.resolve()),
        ]
        proc = subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
        if proc.returncode != 0:
            raise RuntimeError(
                f"FFmpeg could not prepare scene {scene.index}:\n"
                + proc.stderr.decode("utf-8", errors="replace")[-1800:]
            )
        clips.append(target)
    return clips


def professional_combine_filter(self, project: Project, transitions: bool, burn_captions: bool):
    n = len(project.scenes)
    filters: list[str] = []
    for i in range(n):
        filters.append(f"[{i}:v]format=yuv420p,setpts=PTS-STARTPTS[v{i}]")
    if n == 1:
        current = "[v0]"
    else:
        plan = getattr(self, "_zr_transition_plan", _story_transition_plan(self, project, transitions))
        current = "[v0]"
        first_extra = plan[0][1] if plan and plan[0][0] != "cut" else 0.0
        current_duration = max(0.25, project.scenes[0].duration + first_extra)
        for i in range(1, n):
            kind, duration, _label = plan[i - 1]
            out = f"[edit{i}]"
            next_extra = plan[i][1] if i < len(plan) and plan[i][0] != "cut" else 0.0
            next_duration = max(0.25, project.scenes[i].duration + next_extra)
            if kind == "cut" or duration <= 0:
                filters.append(f"{current}[v{i}]concat=n=2:v=1:a=0{out}")
                current_duration += next_duration
            else:
                offset = max(0.0, current_duration - duration)
                filters.append(
                    f"{current}[v{i}]xfade=transition={kind}:duration={duration:.3f}:offset={offset:.3f}{out}"
                )
                current_duration = current_duration + next_duration - duration
            current = out
    if burn_captions:
        filters.append(f"{current}{professional_caption_filter(self)}[vout]")
        current = "[vout]"
    return ";".join(filters), current


def _choose_music(settings, project: Project) -> Path | None:
    root = Path(settings.music_dir).expanduser() if settings.music_dir else None
    if not root or not root.exists() or not root.is_dir():
        return None
    tracks = sorted(path for path in root.iterdir() if path.is_file() and path.suffix.lower() in AUDIO_EXTENSIONS)
    if not tracks:
        return None
    digest = hashlib.sha256(project.topic.encode("utf-8", errors="ignore")).digest()
    return tracks[int.from_bytes(digest[:4], "big") % len(tracks)]


def _postmix_audio(self, project: Project, video: Path) -> None:
    mode = getattr(self, "_zr_soundtrack_mode", "Off")
    sfx_enabled = bool(getattr(self, "_zr_sfx", False))
    if mode == "Off" and not sfx_enabled:
        project.soundtrack_used = "Off"
        return

    ffmpeg = self._ffmpeg()
    duration = max(1.0, sum(scene.duration for scene in project.scenes))
    command: list[str] = [ffmpeg, "-y", "-i", str(video.resolve())]
    filters: list[str] = ["[0:a]asplit=2[narr][side]"]
    next_input = 1
    bed_label = None

    if mode == "Local Music Folder":
        track = _choose_music(self.settings, project)
        if track:
            command += ["-stream_loop", "-1", "-i", str(track.resolve())]
            filters.append(
                f"[{next_input}:a]atrim=0:{duration:.3f},asetpts=PTS-STARTPTS,volume=0.12[musicraw]"
            )
            filters.append("[musicraw][side]sidechaincompress=threshold=0.025:ratio=8:attack=18:release=280[bed]")
            bed_label = "[bed]"
            project.soundtrack_used = track.name
            next_input += 1
        else:
            mode = "Auto Ambience"

    if mode == "Auto Ambience":
        command += ["-f", "lavfi", "-i", f"anoisesrc=color=pink:sample_rate=48000:duration={duration:.3f}"]
        filters.append(
            f"[{next_input}:a]highpass=f=75,lowpass=f=1250,volume=0.010[ambientraw]"
        )
        filters.append("[ambientraw][side]sidechaincompress=threshold=0.025:ratio=8:attack=20:release=300[bed]")
        bed_label = "[bed]"
        project.soundtrack_used = "Auto Ambience"
        next_input += 1

    if bed_label:
        filters.append(f"[narr]{bed_label}amix=inputs=2:normalize=0:weights='1 0.85'[baseaudio]")
        current_audio = "[baseaudio]"
    else:
        current_audio = "[narr]"
        project.soundtrack_used = "Off"

    sfx_labels: list[str] = []
    if sfx_enabled and len(project.scenes) > 2:
        boundaries: list[float] = []
        cursor = 0.0
        for i, scene in enumerate(project.scenes[:-1]):
            cursor += scene.duration
            if i in {2, 5, 8, 11} or scene.transition_to_next not in {"Clean Cut", "End", ""}:
                boundaries.append(cursor)
        boundaries = boundaries[:3]
        for idx, when in enumerate(boundaries):
            command += ["-f", "lavfi", "-i", "anoisesrc=color=white:sample_rate=48000:duration=0.16"]
            delay = max(0, int((when - 0.08) * 1000))
            label = f"[sfx{idx}]"
            filters.append(
                f"[{next_input}:a]highpass=f=1800,lowpass=f=6200,afade=t=in:st=0:d=0.025,"
                f"afade=t=out:st=0.055:d=0.105,volume=0.012,adelay={delay}|{delay}{label}"
            )
            sfx_labels.append(label)
            next_input += 1

    if sfx_labels:
        joined = current_audio + "".join(sfx_labels)
        filters.append(f"{joined}amix=inputs={1 + len(sfx_labels)}:normalize=0,alimiter=limit=0.95[aout]")
    else:
        filters.append(f"{current_audio}alimiter=limit=0.95[aout]")

    temp = video.with_name(video.stem + "_audio_polish.mp4")
    command += [
        "-filter_complex", ";".join(filters),
        "-map", "0:v:0", "-map", "[aout]",
        "-c:v", "copy", "-c:a", "aac", "-b:a", "160k", "-shortest", "-movflags", "+faststart",
        str(temp.resolve()),
    ]
    proc = subprocess.run(command, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    if proc.returncode == 0 and temp.exists() and temp.stat().st_size > 10000:
        temp.replace(video)
    else:
        try:
            temp.unlink(missing_ok=True)
        except OSError:
            pass
        project.soundtrack_used += " (mix fallback)"


def install() -> None:
    original_render = services.FFmpegRenderer.render

    services.CaptionService.generate_from_scenes = professional_captions
    services.FFmpegRenderer._caption_filter = professional_caption_filter
    services.FFmpegRenderer._render_scene_clips = professional_render_scene_clips
    services.FFmpegRenderer._combine_filter = professional_combine_filter

    def render(
        self,
        project,
        audio,
        captions,
        out_dir,
        motion=True,
        transitions=True,
        caption_position="Bottom",
        caption_size="Small",
        transition_style="Story Rhythm",
    ):
        self._zr_project_style = project.style
        self._zr_transition_style = transition_style
        if captions:
            self._zr_caption_filename = Path(captions).name
        callback = getattr(self, "_zr_progress", None)
        result = original_render(
            self,
            project,
            audio,
            captions,
            out_dir,
            motion=motion,
            transitions=transitions,
            caption_position=caption_position,
            caption_size=caption_size,
            transition_style=transition_style,
        )
        video, burned = result
        if callback and (getattr(self, "_zr_soundtrack_mode", "Off") != "Off" or getattr(self, "_zr_sfx", False)):
            callback(97, "Mixing soundtrack, ducking and subtle SFX")
        _postmix_audio(self, project, Path(video))
        if callback:
            callback(98, f"Audio polish ready • {project.soundtrack_used}")
        return video, burned

    services.FFmpegRenderer.render = render
