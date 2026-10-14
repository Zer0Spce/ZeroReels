from __future__ import annotations

from pathlib import Path
import hashlib
import re
import subprocess

from . import services, v060_render
from .models import Project
from .v060_story import keyword_for_phrase


AUDIO_EXTENSIONS = {".mp3", ".wav", ".m4a", ".aac", ".flac", ".ogg"}


def _ass_time(seconds: float) -> str:
    cs = max(0, int(round(seconds * 100)))
    h, cs = divmod(cs, 360000)
    m, cs = divmod(cs, 6000)
    s, cs = divmod(cs, 100)
    return f"{h}:{m:02d}:{s:02d}.{cs:02d}"


def _groups(text: str, max_words: int = 4) -> list[list[str]]:
    words = " ".join((text or "").split()).split()
    groups: list[list[str]] = []
    current: list[str] = []
    for word in words:
        current.append(word)
        strong = bool(re.search(r"[.!?…][\"')\]]?$", word))
        soft = bool(re.search(r"[,;:—][\"')\]]?$", word))
        if (strong and len(current) >= 2) or (soft and len(current) >= 3) or len(current) >= max_words:
            groups.append(current)
            current = []
    if current:
        if groups and len(current) == 1 and len(groups[-1]) < max_words:
            groups[-1].extend(current)
        else:
            groups.append(current)
    return groups


def _escape(text: str) -> str:
    return text.replace("{", "(").replace("}", ")").replace("\n", " ")


def _emphasize(text: str) -> str:
    clean = _escape(text)
    keyword = keyword_for_phrase(clean)
    if not keyword:
        return clean
    match = re.search(rf"\b{re.escape(keyword)}\b", clean, flags=re.IGNORECASE)
    if not match:
        return clean
    yellow = r"{\1c&H0045C9F6&\bord4}"
    white = r"{\1c&H00FFFFFF&\bord4}"
    return clean[:match.start()] + yellow + clean[match.start():match.end()] + white + clean[match.end():]


def _margin_for(position: str, height: int, scene_role: str) -> int:
    if position == "Auto Safe":
        # Without running a heavy face detector, use the director's shot role as a stable
        # proxy: human/action shots get more lower-frame breathing room than wide B-roll.
        if scene_role in {"Hook", "Action", "Escalation", "Peak"}:
            return 168
        if scene_role in {"Detail", "Landing"}:
            return 140
        return 112
    return {"Bottom": 118, "Safe Lower": 190, "Center-Lower": int(height * 0.28)}.get(position, 118)


def speech_paced_captions(self, project: Project, out_dir: Path) -> Path:
    style_name = getattr(self, "_zr_caption_style", "TikTok Pop")
    position = getattr(self, "_zr_caption_position", "Auto Safe")
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
Style: ZeroReels,Segoe UI Semibold,{base_size},&H00FFFFFF,&H0045C9F6,&HCC000000,&H50000000,{bold},0,0,0,100,100,0,0,1,{outline},{shadow},2,70,70,118,1

[Events]
Format: Layer,Start,End,Style,Name,MarginL,MarginR,MarginV,Effect,Text
"""
    lines = [header]
    cursor = 0.0
    for scene in project.scenes:
        max_words = 4 if style_name == "TikTok Pop" else 6
        groups = _groups(scene.narration, max_words)
        if not groups:
            cursor += scene.duration
            continue
        # Character length gives punctuation-heavy phrases slightly more time than a pure word count.
        weights = [max(1.0, len(" ".join(group)) ** 0.72) for group in groups]
        total = sum(weights) or 1.0
        used = 0.0
        margin = _margin_for(position, height, scene.shot_role)
        for idx, (group, weight) in enumerate(zip(groups, weights)):
            duration = max(0.34, scene.duration * weight / total)
            start = cursor + used
            end = cursor + scene.duration if idx == len(groups) - 1 else min(cursor + scene.duration, start + duration)
            phrase = " ".join(group)
            long_phrase = len(phrase) > 23
            shrink = r"{\fs-4}" if long_phrase else ""
            if style_name == "TikTok Pop":
                text = r"{\fad(55,70)\fscx94\fscy94\t(0,110,\fscx100\fscy100)}" + shrink + _emphasize(phrase)
            elif style_name == "Clean Lower Third":
                text = r"{\fad(60,80)}" + shrink + _emphasize(phrase)
            else:
                text = r"{\fad(80,90)}" + shrink + _escape(phrase)
            lines.append(
                f"Dialogue: 0,{_ass_time(start)},{_ass_time(end)},ZeroReels,,0,0,{margin},,{text}\n"
            )
            used = end - cursor
        cursor += scene.duration
    path = out_dir / "captions.ass"
    path.write_text("".join(lines), encoding="utf-8-sig")
    return path


def _choose_music(settings, project: Project) -> Path | None:
    root = Path(settings.music_dir).expanduser() if settings.music_dir else None
    if not root or not root.exists() or not root.is_dir():
        return None
    tracks = sorted(path for path in root.rglob("*") if path.is_file() and path.suffix.lower() in AUDIO_EXTENSIONS)
    if not tracks:
        return None
    key = f"{project.topic}|{project.style}|{project.title}".encode("utf-8", errors="ignore")
    return tracks[int(hashlib.sha256(key).hexdigest()[:8], 16) % len(tracks)]


def _soundscape_kind(project: Project) -> tuple[str, str, str]:
    text = f"{project.topic} {project.script}".lower()
    if any(word in text for word in ("rain", "storm", "ocean", "sea", "water", "river", "flood")):
        return "Water / Rain", "pink", "highpass=f=120,lowpass=f=4200,volume=0.010"
    if any(word in text for word in ("city", "traffic", "street", "crowd", "subway", "train")):
        return "Urban Air", "brown", "highpass=f=70,lowpass=f=2100,volume=0.009"
    if any(word in text for word in ("space", "planet", "earth", "technology", "machine", "computer", "robot", "engine")):
        return "Low Tech Atmosphere", "pink", "highpass=f=45,lowpass=f=900,volume=0.008"
    if any(word in text for word in ("plane", "aircraft", "aviation", "wind", "sky", "mountain")):
        return "Air / Wind", "pink", "highpass=f=180,lowpass=f=3000,volume=0.0085"
    if any(word in text for word in ("mystery", "dark", "abandoned", "ghost", "strange", "secret")):
        return "Dark Room Tone", "brown", "highpass=f=45,lowpass=f=750,volume=0.0075"
    return "Room Tone", "pink", "highpass=f=85,lowpass=f=1650,volume=0.0065"


def human_touch_postmix(self, project: Project, video: Path) -> None:
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
            filters.append(f"[{next_input}:a]atrim=0:{duration:.3f},asetpts=PTS-STARTPTS,volume=0.115[musicraw]")
            filters.append("[musicraw][side]sidechaincompress=threshold=0.024:ratio=7:attack=22:release=360[bed]")
            bed_label = "[bed]"
            project.soundtrack_used = track.name
            next_input += 1
        else:
            mode = "Smart Soundscape"

    if mode in {"Smart Soundscape", "Auto Ambience"}:
        name, color, shaping = _soundscape_kind(project) if mode == "Smart Soundscape" else ("Auto Ambience", "pink", "highpass=f=75,lowpass=f=1250,volume=0.008")
        command += ["-f", "lavfi", "-i", f"anoisesrc=color={color}:sample_rate=48000:duration={duration:.3f}"]
        filters.append(f"[{next_input}:a]{shaping}[ambientraw]")
        filters.append("[ambientraw][side]sidechaincompress=threshold=0.024:ratio=7:attack=24:release=380[bed]")
        bed_label = "[bed]"
        project.soundtrack_used = name
        next_input += 1

    current = "[narr]"
    if bed_label:
        filters.append(f"[narr]{bed_label}amix=inputs=2:normalize=0:weights='1 0.82'[mixbase]")
        current = "[mixbase]"

    # Sparse sound punctuation only at editorial peaks, not every cut.
    sfx_labels: list[str] = []
    if sfx_enabled and len(project.scenes) > 2:
        cursor = 0.0
        selected: list[float] = []
        for scene in project.scenes[:-1]:
            cursor += scene.duration
            if scene.shot_role in {"Peak", "Escalation"} and len(selected) < 2:
                selected.append(cursor)
        for idx, when in enumerate(selected):
            command += ["-f", "lavfi", "-i", "anoisesrc=color=white:sample_rate=48000:duration=0.20"]
            delay = max(0, int((when - 0.10) * 1000))
            label = f"[sfx{idx}]"
            filters.append(
                f"[{next_input}:a]highpass=f=1300,lowpass=f=5200,afade=t=in:st=0:d=0.035,"
                f"afade=t=out:st=0.075:d=0.125,volume=0.009,adelay={delay}|{delay}{label}"
            )
            sfx_labels.append(label)
            next_input += 1
    if sfx_labels:
        filters.append(f"{current}{''.join(sfx_labels)}amix=inputs={1 + len(sfx_labels)}:normalize=0,alimiter=limit=0.96[aout]")
    else:
        filters.append(f"{current}alimiter=limit=0.96[aout]")

    temp = video.with_name(video.stem + "_human_audio.mp4")
    command += [
        "-filter_complex", ";".join(filters), "-map", "0:v:0", "-map", "[aout]",
        "-c:v", "copy", "-c:a", "aac", "-b:a", "192k", "-shortest", "-movflags", "+faststart", str(temp.resolve()),
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


def human_touch_render(
    self,
    project,
    audio: Path,
    captions: Path | None,
    out_dir: Path,
    motion=True,
    transitions=True,
    caption_position="Auto Safe",
    caption_size="Small",
    transition_style="Story Rhythm",
):
    if not project.scenes:
        raise RuntimeError("Project has no scenes to render")
    self._zr_caption_position = caption_position
    self._zr_caption_size = caption_size
    self._zr_transition_style = transition_style
    if captions:
        self._zr_caption_filename = Path(captions).name
    callback = getattr(self, "_zr_progress", None)
    ffmpeg = self._ffmpeg()
    output = out_dir / "final.mp4"
    if callback:
        callback(82, "Editing visual rhythm and adaptive motion")
    clips = self._render_scene_clips(project, out_dir, motion, transitions)

    def run(burn: bool):
        cmd: list[str] = [ffmpeg, "-y"]
        for clip in clips:
            cmd += ["-i", str(Path(clip).resolve())]
        audio_index = len(clips)
        cmd += ["-i", str(Path(audio).resolve())]
        graph, video_label = self._combine_filter(project, transitions, burn)
        # v0.7 deliberately backs away from the old 2.2:1 compressor. A gentler 1.45:1
        # ratio plus wider loudness range keeps sentence emphasis and pauses alive.
        graph += (
            f";[{audio_index}:a]highpass=f=55,"
            "equalizer=f=3000:t=q:w=1.1:g=1.0,"
            "acompressor=threshold=-16dB:ratio=1.45:attack=35:release=260:makeup=1.0,"
            "loudnorm=I=-16:TP=-1.3:LRA=11[aout]"
        )
        cmd += [
            "-filter_complex", graph, "-map", video_label, "-map", "[aout]",
            "-c:v", "libx264", "-preset", "veryfast", "-crf", "19", "-pix_fmt", "yuv420p",
            "-c:a", "aac", "-b:a", "192k", "-shortest", "-movflags", "+faststart", str(output.resolve()),
        ]
        return subprocess.run(cmd, cwd=str(out_dir), stdout=subprocess.PIPE, stderr=subprocess.PIPE)

    want = bool(captions and Path(captions).exists())
    if callback:
        callback(93, "Compositing mostly-clean cuts and speech-paced captions")
    proc = run(want)
    burned = want
    if proc.returncode != 0 and want:
        proc = run(False)
        burned = False
    if proc.returncode != 0:
        raise RuntimeError("FFmpeg render failed:\n" + proc.stderr.decode("utf-8", errors="replace")[-2600:])
    for clip in clips:
        try:
            Path(clip).unlink()
        except OSError:
            pass
    if callback:
        callback(97, "Mixing semantic room tone, ducking and sparse SFX")
    human_touch_postmix(self, project, output)
    if callback:
        callback(98, f"Sound design ready • {project.soundtrack_used}")
    return output, burned


def install() -> None:
    services.CaptionService.generate_from_scenes = speech_paced_captions
    services.FFmpegRenderer.render = human_touch_render
