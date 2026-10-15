from __future__ import annotations

from pathlib import Path
import subprocess

from . import services
from .models import Project
from .v060_render import _motion_filter, _story_transition_plan
from .win_subprocess import run_hidden


def _full_frame_real_filter(width: int, height: int, frames: int, motion: bool, index: int) -> str:
    """Fill the delivery frame edge-to-edge. No blurred matte/background layer."""
    base = (
        f"scale={width}:{height}:force_original_aspect_ratio=increase,"
        f"crop={width}:{height}:(iw-{width})/2:(ih-{height})/2,"
        "setsar=1,eq=contrast=1.02:saturation=1.0,unsharp=5:5:0.10:5:5:0.0"
    )
    if not motion:
        return base + ",fps=30,format=yuv420p"

    # Gentle movement after the cover crop. Alternate direction so archival/web scenes do not
    # feel like identical Ken Burns shots while always keeping the full vertical canvas filled.
    if index % 3 == 0:
        x = "iw/2-(iw/zoom/2)"
        y = "ih/2-(ih/zoom/2)"
        z = "min(zoom+0.00010,1.018)"
    elif index % 3 == 1:
        x = "min(max(0,(iw-iw/zoom)*on/max(1,duration*30)),iw-iw/zoom)"
        y = "ih/2-(ih/zoom/2)"
        z = "1.012"
    else:
        x = "max(0,(iw-iw/zoom)*(1-on/max(1,duration*30)))"
        y = "ih/2-(ih/zoom/2)"
        z = "1.012"
    # zoompan does not expose the scene duration symbol inside expressions consistently across
    # FFmpeg builds, so use frame count directly for the directional variants.
    if index % 3 == 1:
        x = f"min(max(0,(iw-iw/zoom)*on/{max(1, frames)}),iw-iw/zoom)"
    elif index % 3 == 2:
        x = f"max(0,(iw-iw/zoom)*(1-on/{max(1, frames)}))"
    return base + f",zoompan=z='{z}':x='{x}':y='{y}':d=1:s={width}x{height}:fps=30,setsar=1,format=yuv420p"


def full_frame_scene_clips(self, project: Project, out_dir: Path, motion: bool, transitions: bool):
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

        if scene.source_type == "Wikimedia Commons":
            vf = _full_frame_real_filter(width, height, frames, motion, i)
            scene.motion_style = "Full-frame cover + subtle motion" if motion else "Full-frame cover"
        else:
            vf = _motion_filter(scene, width, height, frames, motion) + ",setsar=1"

        scene.transition_to_next = plan[i][2] if i < len(plan) else "End"
        if callback:
            source = "real" if scene.source_type == "Wikimedia Commons" else "AI"
            callback(
                84 + int(6 * i / max(1, len(project.scenes))),
                f"Editing scene {i + 1}/{len(project.scenes)} • {source} • {scene.motion_style}",
            )

        cmd = [
            ffmpeg, "-y", "-loop", "1", "-framerate", "30", "-t", f"{duration:.3f}",
            "-i", str(Path(scene.image_path).resolve()), "-vf", vf, "-r", "30", "-an",
            "-c:v", "libx264", "-preset", "veryfast", "-crf", "19", "-pix_fmt", "yuv420p",
            "-movflags", "+faststart", str(target.resolve()),
        ]
        proc = run_hidden(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
        if proc.returncode != 0:
            raise RuntimeError(
                f"FFmpeg could not prepare scene {scene.index}:\n"
                + proc.stderr.decode("utf-8", errors="replace")[-1800:]
            )
        clips.append(target)
    return clips


def install() -> None:
    services.FFmpegRenderer._render_scene_clips = full_frame_scene_clips
