from __future__ import annotations

from pathlib import Path
import re
import subprocess

from . import services, v060_render


def _combine_filter_cfr(self, project, transitions: bool, burn_captions: bool):
    """Preserve the CFR metadata FFmpeg 7.1 needs for xfade.

    The scene clips are already 30fps and start at zero. Running setpts/fps on each
    xfade input can clear link frame_rate to 0/0 on FFmpeg 7.1, so keep the streams intact.
    """
    n = len(project.scenes)
    filters: list[str] = []
    for i in range(n):
        filters.append(f"[{i}:v]format=yuv420p[v{i}]")
    if n == 1:
        current = "[v0]"
    else:
        plan = getattr(self, "_zr_transition_plan", v060_render._story_transition_plan(self, project, transitions))
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
        filters.append(f"{current}{v060_render.professional_caption_filter(self)}[vout]")
        current = "[vout]"
    return ";".join(filters), current


def _safe_postmix_audio(self, project, video: Path) -> None:
    mode = getattr(self, "_zr_soundtrack_mode", "Off")
    sfx_enabled = bool(getattr(self, "_zr_sfx", False))
    if mode == "Off" and not sfx_enabled:
        project.soundtrack_used = "Off"
        return

    ffmpeg = self._ffmpeg()
    duration = max(1.0, sum(scene.duration for scene in project.scenes))
    command: list[str] = [ffmpeg, "-y", "-i", str(video.resolve())]
    needs_sidechain = mode in {"Auto Ambience", "Local Music Folder"}
    filters: list[str] = ["[0:a]asplit=2[narr][side]" if needs_sidechain else "[0:a]anull[narr]"]
    next_input = 1
    bed_label = None

    if mode == "Local Music Folder":
        track = v060_render._choose_music(self.settings, project)
        if track:
            command += ["-stream_loop", "-1", "-i", str(track.resolve())]
            filters.append(f"[{next_input}:a]atrim=0:{duration:.3f},asetpts=PTS-STARTPTS,volume=0.12[musicraw]")
            filters.append("[musicraw][side]sidechaincompress=threshold=0.025:ratio=8:attack=18:release=280[bed]")
            bed_label = "[bed]"
            project.soundtrack_used = track.name
            next_input += 1
        else:
            mode = "Auto Ambience"

    if mode == "Auto Ambience":
        command += ["-f", "lavfi", "-i", f"anoisesrc=color=pink:sample_rate=48000:duration={duration:.3f}"]
        filters.append(f"[{next_input}:a]highpass=f=75,lowpass=f=1250,volume=0.010[ambientraw]")
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
        for idx, when in enumerate(boundaries[:3]):
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
        filters.append(
            f"{current_audio}{''.join(sfx_labels)}amix=inputs={1 + len(sfx_labels)}:normalize=0,alimiter=limit=0.95[aout]"
        )
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
    # Keep deterministic FLUX seeds at the very end of prompts, where the existing
    # Comfy workflow parser expects them.
    original_script_generate = services.ScriptService.generate

    def script_generate(self, project, scene_count: int):
        script, scenes = original_script_generate(self, project, scene_count)
        for scene in scenes:
            matches = re.findall(r"\[ZR-SEED=(\d+)\]", scene.image_prompt)
            if matches:
                seed = int(matches[-1])
                scene.seed = seed
                scene.image_prompt = re.sub(r"\s*\[ZR-SEED=\d+\]\s*", " ", scene.image_prompt).strip()
                scene.image_prompt += f" [ZR-SEED={seed}]"
        return script, scenes

    services.ScriptService.generate = script_generate
    services.FFmpegRenderer._combine_filter = _combine_filter_cfr
    v060_render._postmix_audio = _safe_postmix_audio
