from __future__ import annotations

from pathlib import Path
import subprocess
import urllib.request

from PySide6.QtWidgets import QCheckBox, QLabel

from . import pipeline, services, ui, v060_render, v071_pipeline, v071_web_media, v080_render, v090_editor
from .models import Project, Scene
from .win_subprocess import run_hidden


_INSTALLED = False


def _download_overlay_video(project: Project, scene: Scene, out_dir: Path) -> Path:
    page, query = v090_editor._video_search(project, scene)
    if page is None:
        raise RuntimeError(f"No matching overlay video found: {query or project.topic}")
    direct, page_url, credit, license_name, mime = v090_editor._video_meta(page)
    if not direct or mime not in v090_editor.VIDEO_MIMES:
        raise RuntimeError("Commons returned an unsupported overlay video")

    request = urllib.request.Request(
        direct,
        headers={"User-Agent": v071_web_media.USER_AGENT, "Accept": "video/*,*/*;q=0.8"},
    )
    with urllib.request.urlopen(request, timeout=90) as response:
        content_length = int(response.headers.get("Content-Length") or 0)
        if content_length and content_length > v090_editor.MAX_VIDEO_BYTES:
            raise RuntimeError("Overlay video exceeds the 80 MB scene limit")
        data = response.read(v090_editor.MAX_VIDEO_BYTES + 1)
    if len(data) > v090_editor.MAX_VIDEO_BYTES:
        raise RuntimeError("Overlay video exceeds the 80 MB scene limit")
    if len(data) < 8192:
        raise RuntimeError("Commons returned an invalid/empty overlay video")

    target = out_dir / f"scene_{scene.index:03d}_overlay{v090_editor.VIDEO_MIMES[mime]}"
    target.write_bytes(data)
    scene.overlay_video_path = str(target)
    scene.overlay_source_url = page_url or direct
    scene.overlay_source_credit = credit or v071_web_media._clean_html(str(page.get("title", "")))
    scene.overlay_source_license = license_name or "See source page"
    scene.overlay_source_query = f"Video overlay: {query}"
    scene.quality_notes = [
        *[note for note in scene.quality_notes if "motion overlay" not in note.lower()],
        f"motion overlay • {scene.overlay_source_license}",
    ][:3]
    return target


def _should_overlay(project: Project, scene: Scene) -> bool:
    if not getattr(project, "web_video_overlay", False):
        return False
    if scene.source_type != "Wikimedia Commons" or scene.media_type != "image":
        return False
    role = (scene.shot_role or "").casefold()
    if role in {"detail", "landing"}:
        return False
    return ((scene.index - 1) % 4 == 1) or role in {"escalation", "aftermath"}


def _overlay_generate(self, scene: Scene, out_dir: Path, fmt: str) -> Path:
    original = getattr(_overlay_generate, "_original")
    result = original(self, scene, out_dir, fmt)
    if _should_overlay(self.project, scene):
        try:
            _download_overlay_video(self.project, scene, out_dir)
        except Exception:
            # Never fail a scene because the optional overlay was unavailable.
            scene.overlay_video_path = ""
    return result


def _overlay_filter(width: int, height: int) -> tuple[int, int, int, int]:
    overlay_w = max(320, int(width * 0.88))
    target_h_from_ratio = int(overlay_w * 9 / 16)
    overlay_h = max(180, min(int(height * 0.36), target_h_from_ratio))
    x = max(0, (width - overlay_w) // 2)
    y = max(24, int(height * 0.18))
    return overlay_w, overlay_h, x, y


def render_overlay_scene_clips(self, project: Project, out_dir: Path, motion: bool, transitions: bool):
    ffmpeg = self._ffmpeg()
    width, height = services.dimensions_for(project.format)
    plan = v060_render._story_transition_plan(self, project, transitions)
    self._zr_transition_plan = plan
    clips: list[Path] = []
    callback = getattr(self, "_zr_progress", None)

    for i, scene in enumerate(project.scenes):
        extra = plan[i][1] if i < len(plan) and plan[i][0] != "cut" else 0.0
        duration = max(0.25, scene.duration + extra)
        frames = max(1, int(round(duration * 30)))
        target = out_dir / f"_clip_{scene.index:03d}.mp4"
        source_path = Path(scene.image_path).resolve()
        overlay_path = Path(scene.overlay_video_path).resolve() if scene.overlay_video_path else None

        if overlay_path and overlay_path.exists() and not v090_editor._video_scene(scene):
            bg = v080_render._full_frame_real_filter(width, height, frames, motion, i)
            ow, oh, ox, oy = _overlay_filter(width, height)
            filter_complex = (
                f"[0:v]{bg}[bg];"
                f"[1:v]scale={ow}:{oh}:force_original_aspect_ratio=increase,"
                f"crop={ow}:{oh}:(iw-{ow})/2:(ih-{oh})/2,setsar=1,fps=30,format=yuv420p[ov];"
                f"[bg][ov]overlay={ox}:{oy}:shortest=1,setsar=1,format=yuv420p[outv]"
            )
            cmd = [
                ffmpeg, "-y",
                "-loop", "1", "-framerate", "30", "-t", f"{duration:.3f}", "-i", str(source_path),
                "-stream_loop", "-1", "-i", str(overlay_path),
                "-filter_complex", filter_complex,
                "-map", "[outv]", "-t", f"{duration:.3f}", "-r", "30", "-an",
                "-c:v", "libx264", "-preset", "veryfast", "-crf", "19", "-pix_fmt", "yuv420p",
                "-movflags", "+faststart", str(target.resolve()),
            ]
            scene.motion_style = "Real image + authentic motion overlay"
            source_label = "real image + B-roll overlay"
        elif v090_editor._video_scene(scene):
            scene.media_type = "video"
            vf = v090_editor._video_cover_filter(width, height)
            cmd = [
                ffmpeg, "-y", "-stream_loop", "-1", "-i", str(source_path),
                "-t", f"{duration:.3f}", "-vf", vf, "-r", "30", "-an",
                "-c:v", "libx264", "-preset", "veryfast", "-crf", "19", "-pix_fmt", "yuv420p",
                "-movflags", "+faststart", str(target.resolve()),
            ]
            scene.motion_style = "Authentic B-roll motion"
            source_label = "B-roll video"
        else:
            scene.media_type = "image"
            if scene.source_type in {"Wikimedia Commons", "User Image"}:
                vf = v080_render._full_frame_real_filter(width, height, frames, motion, i)
                scene.motion_style = "Full-frame cover + subtle motion" if motion else "Full-frame cover"
                source_label = "real image" if scene.source_type == "Wikimedia Commons" else "user image"
            else:
                vf = v060_render._motion_filter(scene, width, height, frames, motion) + ",setsar=1"
                source_label = "AI"
            cmd = [
                ffmpeg, "-y", "-loop", "1", "-framerate", "30", "-t", f"{duration:.3f}",
                "-i", str(source_path), "-vf", vf, "-r", "30", "-an",
                "-c:v", "libx264", "-preset", "veryfast", "-crf", "19", "-pix_fmt", "yuv420p",
                "-movflags", "+faststart", str(target.resolve()),
            ]

        scene.transition_to_next = plan[i][2] if i < len(plan) else "End"
        if callback:
            callback(
                84 + int(6 * i / max(1, len(project.scenes))),
                f"Editing scene {i + 1}/{len(project.scenes)} • {source_label} • {scene.motion_style}",
            )
        proc = run_hidden(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
        if proc.returncode != 0:
            raise RuntimeError(
                f"FFmpeg could not prepare scene {scene.index}:\n"
                + proc.stderr.decode("utf-8", errors="replace")[-1800:]
            )
        clips.append(target)
    return clips


def _write_sources_with_overlays(project: Project, out_dir: Path) -> None:
    original = getattr(_write_sources_with_overlays, "_original")
    original(project, out_dir)
    overlays = [scene for scene in project.scenes if scene.overlay_source_url]
    if not overlays:
        return
    path = out_dir / "SOURCES.txt"
    text = path.read_text(encoding="utf-8") if path.exists() else "ZeroReels real-media sources\n============================\n\n"
    lines = [text.rstrip(), "", "Motion overlays", "---------------", ""]
    for scene in overlays:
        lines.extend([
            f"Scene {scene.index:02d} overlay video",
            f"Search: {scene.overlay_source_query}",
            f"Source: {scene.overlay_source_url}",
            f"Credit: {scene.overlay_source_credit or 'See source page'}",
            f"License: {scene.overlay_source_license or 'See source page'}",
            "",
        ])
    path.write_text("\n".join(lines).rstrip() + "\n", encoding="utf-8")


def install() -> None:
    global _INSTALLED
    if _INSTALLED:
        return

    _overlay_generate._original = v090_editor.WikimediaMediaService.generate
    v090_editor.WikimediaMediaService.generate = _overlay_generate
    services.FFmpegRenderer._render_scene_clips = render_overlay_scene_clips

    _write_sources_with_overlays._original = v071_pipeline._write_sources
    v071_pipeline._write_sources = _write_sources_with_overlays

    original_pipeline_run = pipeline.Pipeline.run
    original_create_page = ui.MainWindow._create_page
    original_options = ui.MainWindow._options

    def pipeline_run(self, project, options, progress=lambda value, text: None):
        project.web_video_overlay = bool(getattr(options, "web_video_overlay", True))
        return original_pipeline_run(self, project, options, progress)

    def create_page(self):
        page = original_create_page(self)
        quality = getattr(self, "create_quality_card", None)
        grid = quality.layout() if quality is not None else None
        if grid is not None and hasattr(grid, "addWidget"):
            self.web_video_overlay_check = QCheckBox("Video overlay on real Wikimedia images")
            self.web_video_overlay_check.setChecked(True)
            self.web_video_overlay_check.setToolTip(
                "Keeps the real photo full-frame and adds a related Commons video over the upper-middle of selected scenes. The lower caption-safe area stays clear."
            )
            grid.addWidget(self.web_video_overlay_check, 18, 0, 1, 2)

            def sync_enabled(value: str):
                enabled = value in {"Real Web Images", "Hybrid"}
                self.web_video_overlay_check.setEnabled(enabled)

            if hasattr(self, "image_source_box"):
                self.image_source_box.currentTextChanged.connect(sync_enabled)
                sync_enabled(self.image_source_box.currentText())
            quality.adjustSize()
            quality.setMinimumHeight(max(quality.minimumHeight(), quality.sizeHint().height() + 10))
        return page

    def options(self):
        opts = original_options(self)
        opts.web_video_overlay = bool(
            getattr(self, "web_video_overlay_check", None) and self.web_video_overlay_check.isChecked()
        )
        return opts

    pipeline.Pipeline.run = pipeline_run
    ui.MainWindow._create_page = create_page
    ui.MainWindow._options = options
    _INSTALLED = True
