from __future__ import annotations

from pathlib import Path
import re
import subprocess

from . import services
from .models import Project
from .v060_render import _motion_filter, _story_transition_plan


def _real_media_filter(width: int, height: int, frames: int, motion: bool) -> str:
    """Preserve authentic source framing and normalize every archival clip to SAR 1:1."""
    # The blurred copy fills the delivery canvas. The sharp copy is fully contained, which is
    # much safer for archival landscape photos, maps and historic documentation.
    # IMPORTANT: source photos often carry odd pixel-aspect metadata. FFmpeg concat/xfade
    # requires matching SAR, so the final output is always forced to square pixels.
    base = (
        f"split=2[bg][fg];"
        f"[bg]scale={width}:{height}:force_original_aspect_ratio=increase,crop={width}:{height},"
        "boxblur=24:2,eq=brightness=-0.055:saturation=0.78[bg2];"
        f"[fg]scale={width}:{height}:force_original_aspect_ratio=decrease,"
        "eq=contrast=1.025:saturation=1.0,unsharp=5:5:0.12:5:5:0.0[fg2];"
        f"[bg2][fg2]overlay=(W-w)/2:(H-h)/2"
    )
    if not motion:
        return base + ",setsar=1,fps=30,format=yuv420p"
    # Restrained 1.5% editorial push keeps authentic photography alive without making it seasick.
    return (
        base
        + f",zoompan=z='min(zoom+0.00012,1.015)':x='iw/2-(iw/zoom/2)':"
          f"y='ih/2-(ih/zoom/2)':d=1:s={width}x{height}:fps=30,setsar=1,format=yuv420p"
    )


def reality_render_scene_clips(self, project: Project, out_dir: Path, motion: bool, transitions: bool):
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
            vf = _real_media_filter(width, height, frames, motion)
            scene.motion_style = "Archival fit + subtle push" if motion else "Archival fit"
        else:
            # Defense-in-depth for Hybrid mode: force square pixels on AI clips too.
            vf = _motion_filter(scene, width, height, frames, motion) + ",setsar=1"

        if i < len(plan):
            scene.transition_to_next = plan[i][2]
        else:
            scene.transition_to_next = "End"
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
        proc = subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
        if proc.returncode != 0:
            raise RuntimeError(
                f"FFmpeg could not prepare scene {scene.index}:\n"
                + proc.stderr.decode("utf-8", errors="replace")[-1800:]
            )
        clips.append(target)
    return clips


def _normalize_final_graph_sar(filtergraph: str) -> str:
    """Normalize every scene input again before concat/xfade.

    This protects projects created with older clips and catches codec/container SAR metadata that
    can survive the per-scene render despite identical 1080x1920 dimensions.
    """
    return re.sub(
        r"(\[\d+:v\]format=yuv420p)(,setpts=PTS-STARTPTS)",
        r"\1,setsar=1\2",
        filtergraph,
    )


def install() -> None:
    services.FFmpegRenderer._render_scene_clips = reality_render_scene_clips

    original_combine_filter = services.FFmpegRenderer._combine_filter

    def square_pixel_combine_filter(self, project: Project, transitions: bool, burn_captions: bool):
        filtergraph, output = original_combine_filter(self, project, transitions, burn_captions)
        return _normalize_final_graph_sar(filtergraph), output

    services.FFmpegRenderer._combine_filter = square_pixel_combine_filter
