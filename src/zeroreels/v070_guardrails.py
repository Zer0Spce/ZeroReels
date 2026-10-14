from __future__ import annotations

from pathlib import Path
import subprocess

from . import v070_render


def _sfx_only_postmix(self, project, video: Path) -> None:
    """Mix sparse editorial SFX without creating an unused sidechain branch."""
    if not bool(getattr(self, "_zr_sfx", False)):
        project.soundtrack_used = "Off"
        return
    ffmpeg = self._ffmpeg()
    command: list[str] = [ffmpeg, "-y", "-i", str(video.resolve())]
    filters: list[str] = ["[0:a]anull[narr]"]
    next_input = 1
    cursor = 0.0
    labels: list[str] = []
    for scene in project.scenes[:-1]:
        cursor += scene.duration
        if scene.shot_role not in {"Peak", "Escalation"} or len(labels) >= 2:
            continue
        command += ["-f", "lavfi", "-i", "anoisesrc=color=white:sample_rate=48000:duration=0.20"]
        delay = max(0, int((cursor - 0.10) * 1000))
        label = f"[sfx{len(labels)}]"
        filters.append(
            f"[{next_input}:a]highpass=f=1300,lowpass=f=5200,afade=t=in:st=0:d=0.035,"
            f"afade=t=out:st=0.075:d=0.125,volume=0.009,adelay={delay}|{delay}{label}"
        )
        labels.append(label)
        next_input += 1
    if labels:
        filters.append(f"[narr]{''.join(labels)}amix=inputs={1 + len(labels)}:normalize=0,alimiter=limit=0.96[aout]")
    else:
        filters.append("[narr]alimiter=limit=0.96[aout]")
    temp = video.with_name(video.stem + "_sfx_only.mp4")
    command += [
        "-filter_complex", ";".join(filters), "-map", "0:v:0", "-map", "[aout]",
        "-c:v", "copy", "-c:a", "aac", "-b:a", "192k", "-shortest", "-movflags", "+faststart", str(temp.resolve()),
    ]
    proc = subprocess.run(command, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    if proc.returncode == 0 and temp.exists() and temp.stat().st_size > 10000:
        temp.replace(video)
        project.soundtrack_used = "Off • sparse SFX"
    else:
        try:
            temp.unlink(missing_ok=True)
        except OSError:
            pass
        project.soundtrack_used = "Off • SFX mix fallback"


def install() -> None:
    original = v070_render.human_touch_postmix

    def safe_postmix(self, project, video: Path):
        mode = getattr(self, "_zr_soundtrack_mode", "Off")
        if mode == "Off":
            return _sfx_only_postmix(self, project, Path(video))
        return original(self, project, Path(video))

    v070_render.human_touch_postmix = safe_postmix
