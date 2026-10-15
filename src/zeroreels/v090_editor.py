from __future__ import annotations

from pathlib import Path
import re
import shutil
import subprocess
import urllib.parse
import urllib.request

from PySide6.QtCore import QThread, Qt, Signal
from PySide6.QtGui import QPixmap
from PySide6.QtWidgets import (
    QCheckBox,
    QFileDialog,
    QHBoxLayout,
    QInputDialog,
    QLabel,
    QMessageBox,
    QProgressBar,
    QVBoxLayout,
)

from . import pipeline, services, ui, v060_render, v070_voice, v071_pipeline, v071_web_media, v080_render
from .models import Project, Scene
from .win_subprocess import run_hidden


VIDEO_MIMES = {
    "video/webm": ".webm",
    "video/ogg": ".ogv",
    "video/mp4": ".mp4",
}
VIDEO_SUFFIXES = {".webm", ".ogv", ".ogg", ".mp4", ".mov", ".mkv", ".m4v"}
MAX_VIDEO_BYTES = 80 * 1024 * 1024
_INSTALLED = False


def _is_video_path(path: str | Path) -> bool:
    return Path(path).suffix.lower() in VIDEO_SUFFIXES


def _video_scene(scene: Scene) -> bool:
    return scene.media_type == "video" or scene.source_type in {"Wikimedia Commons Video", "User Video"} or _is_video_path(scene.image_path)


def _tokens(text: str) -> set[str]:
    return {
        token.casefold()
        for token in re.findall(r"[A-Za-z0-9][A-Za-z0-9'’-]{2,}", text or "")
        if token.casefold() not in v071_web_media.STOPWORDS and len(token) >= 3
    }


def _video_queries(project: Project, scene: Scene) -> list[str]:
    """Build scene-first B-roll searches, then broaden safely back to the main topic."""
    subject = v071_web_media.primary_subject(project)
    scene_words = v071_web_media._keywords(scene.narration, 7)
    prompt_words = v071_web_media._keywords(scene.image_prompt, 5)
    cleaned_topic = v071_web_media._topic_subject(project.topic)
    candidates: list[str] = []

    # The first searches describe the exact spoken beat, not the full narration sentence.
    if subject and scene_words:
        candidates.append(" ".join([subject, *scene_words[:3]]))
        candidates.append(" ".join([subject, *scene_words[:2]]))
    if subject and prompt_words:
        candidates.append(" ".join([subject, *prompt_words[:2]]))
    if scene_words:
        candidates.append(" ".join(scene_words[:4]))
    if subject:
        candidates.append(subject)
    if cleaned_topic:
        candidates.append(cleaned_topic)

    unique: list[str] = []
    seen: set[str] = set()
    for candidate in candidates:
        value = " ".join(candidate.split()).strip()
        key = value.casefold()
        if value and key not in seen:
            seen.add(key)
            unique.append(value)
    return unique


def _video_page_score(page: dict, project: Project, scene: Scene, query: str) -> int:
    """Prefer clips whose title/description overlap the actual subject and narration beat."""
    info = (page.get("imageinfo") or [{}])[0]
    meta = info.get("extmetadata", {}) or {}
    description = " ".join([
        str(page.get("title", "")),
        v071_web_media._clean_html(str((meta.get("ObjectName") or {}).get("value", ""))),
        v071_web_media._clean_html(str((meta.get("ImageDescription") or {}).get("value", ""))),
        v071_web_media._clean_html(str((meta.get("Categories") or {}).get("value", ""))),
    ])
    hay = _tokens(description)
    if not hay:
        return 0
    subject_terms = _tokens(v071_web_media.primary_subject(project))
    scene_terms = _tokens(scene.narration)
    query_terms = _tokens(query)
    score = 0
    score += 5 * len(subject_terms & hay)
    score += 3 * len(scene_terms & hay)
    score += 2 * len(query_terms & hay)
    # Exact phrase-ish title relevance is particularly useful for named people/events.
    title = str(page.get("title", "")).casefold()
    subject = v071_web_media.primary_subject(project).casefold().strip()
    if subject and subject in title:
        score += 8
    return score


def _video_search(project: Project, scene: Scene) -> tuple[dict, str] | tuple[None, str]:
    """Return a license-traceable Commons video that actually fits the current narration beat."""
    attempts: list[str] = []
    for query in _video_queries(project, scene)[:6]:
        attempts.append(query)
        params = {
            "action": "query",
            "generator": "search",
            "gsrsearch": f"{query} filetype:video",
            "gsrnamespace": 6,
            "gsrlimit": 40,
            "prop": "imageinfo",
            "iiprop": "url|mime|size|extmetadata",
            "format": "json",
            "origin": "*",
        }
        url = "https://commons.wikimedia.org/w/api.php?" + urllib.parse.urlencode(params)
        try:
            data = v071_web_media._json(url, timeout=30)
        except Exception:
            continue
        pages = list(data.get("query", {}).get("pages", {}).values())
        ranked: list[tuple[int, int, dict]] = []
        for page in pages:
            info_rows = page.get("imageinfo", []) or []
            if not info_rows:
                continue
            info = info_rows[0]
            mime = str(info.get("mime", "")).lower()
            direct = str(info.get("url", ""))
            if mime not in VIDEO_MIMES or not direct:
                continue
            size = int(info.get("size") or 0)
            if size and size > MAX_VIDEO_BYTES:
                continue
            score = _video_page_score(page, project, scene, query)
            if score < 3:
                continue
            ranked.append((score, -int(page.get("index", 9999)), page))
        if ranked:
            ranked.sort(key=lambda row: (row[0], row[1]), reverse=True)
            return ranked[0][2], query
    return None, " | ".join(attempts)


def _video_meta(page: dict) -> tuple[str, str, str, str, str]:
    info = (page.get("imageinfo") or [{}])[0]
    meta = info.get("extmetadata", {}) or {}
    direct = str(info.get("url", ""))
    page_url = str(info.get("descriptionurl", ""))
    mime = str(info.get("mime", "")).lower()
    artist = v071_web_media._clean_html(str((meta.get("Artist") or {}).get("value", "")))
    credit = v071_web_media._clean_html(str((meta.get("Credit") or {}).get("value", "")))
    license_name = v071_web_media._clean_html(str((meta.get("LicenseShortName") or {}).get("value", "")))
    return direct, page_url, artist or credit, license_name, mime


def _download_video(project: Project, scene: Scene, out_dir: Path) -> Path:
    page, query = _video_search(project, scene)
    if page is None:
        raise RuntimeError(f"No topic-matched Commons B-roll video found: {query or project.topic}")
    direct, page_url, credit, license_name, mime = _video_meta(page)
    if not direct or mime not in VIDEO_MIMES:
        raise RuntimeError("Commons returned an unsupported B-roll video")

    request = urllib.request.Request(
        direct,
        headers={"User-Agent": v071_web_media.USER_AGENT, "Accept": "video/*,*/*;q=0.8"},
    )
    with urllib.request.urlopen(request, timeout=90) as response:
        content_length = int(response.headers.get("Content-Length") or 0)
        if content_length and content_length > MAX_VIDEO_BYTES:
            raise RuntimeError("Commons B-roll video exceeds the 80 MB scene limit")
        data = response.read(MAX_VIDEO_BYTES + 1)
    if len(data) > MAX_VIDEO_BYTES:
        raise RuntimeError("Commons B-roll video exceeds the 80 MB scene limit")
    if len(data) < 8192:
        raise RuntimeError("Commons returned an invalid/empty B-roll video")

    target = out_dir / f"scene_{scene.index:03d}_broll{VIDEO_MIMES[mime]}"
    target.write_bytes(data)
    scene.image_path = str(target)
    scene.media_type = "video"
    scene.source_type = "Wikimedia Commons Video"
    scene.source_url = page_url or direct
    scene.source_credit = credit or v071_web_media._clean_html(str(page.get("title", "")))
    scene.source_license = license_name or "See source page"
    scene.source_query = f"Topic-matched video: {query}"
    scene.quality_score = 100
    scene.quality_notes = [
        f"topic-matched motion B-roll • {scene.source_license}",
        f"credit: {scene.source_credit or 'see source page'}",
    ]
    scene.status = "image-ready"
    return target


class WikimediaMediaService(v071_web_media.WikimediaImageService):
    """Use a few scene-matched real videos, then the proven Commons still-image path."""

    def __init__(self, project: Project):
        super().__init__(project)
        self.video_count = 0
        self.video_limit = max(2, min(5, max(1, len(project.scenes) // 3)))

    def _wants_motion(self, scene: Scene) -> bool:
        if not getattr(self.project, "web_video_broll", False):
            return False
        if self.video_count >= self.video_limit:
            return False
        role = (scene.shot_role or "").casefold()
        energetic = role in {"action", "escalation", "peak", "establishing", "aftermath"}
        cadence_slot = ((scene.index - 1) % 3 == 0)
        return energetic and (cadence_slot or role in {"action", "peak"})

    def generate(self, scene: Scene, out_dir: Path, fmt: str) -> Path:
        if self._wants_motion(scene):
            try:
                result = _download_video(self.project, scene, out_dir)
                self.video_count += 1
                return result
            except Exception:
                # A weak/missing video match is not accepted and never kills the project.
                # Fall back to a relevant still rather than forcing unrelated motion footage.
                pass
        result = super().generate(scene, out_dir, fmt)
        scene.media_type = "image"
        return result


def _video_cover_filter(width: int, height: int) -> str:
    return (
        f"scale={width}:{height}:force_original_aspect_ratio=increase,"
        f"crop={width}:{height}:(iw-{width})/2:(ih-{height})/2,"
        "setsar=1,fps=30,eq=contrast=1.02:saturation=1.01,unsharp=5:5:0.08:5:5:0.0,format=yuv420p"
    )


def render_media_scene_clips(self, project: Project, out_dir: Path, motion: bool, transitions: bool):
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

        if _video_scene(scene):
            scene.media_type = "video"
            scene.motion_style = "Topic-matched authentic B-roll"
            vf = _video_cover_filter(width, height)
            cmd = [
                ffmpeg, "-y", "-stream_loop", "-1", "-i", str(source_path),
                "-t", f"{duration:.3f}", "-vf", vf, "-r", "30", "-an",
                "-c:v", "libx264", "-preset", "veryfast", "-crf", "19", "-pix_fmt", "yuv420p",
                "-movflags", "+faststart", str(target.resolve()),
            ]
            source_label = "topic B-roll video"
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


def _quality_summary(project: Project) -> str:
    total = len(project.scenes)
    if not total:
        return "No scenes"
    warnings = sum(1 for scene in project.scenes if scene.status == "image-warning")
    real_video = sum(1 for scene in project.scenes if scene.source_type == "Wikimedia Commons Video")
    real_image = sum(1 for scene in project.scenes if scene.source_type == "Wikimedia Commons")
    ai = sum(1 for scene in project.scenes if scene.source_type == "AI Generated")
    user = total - real_video - real_image - ai
    parts = [f"{total - warnings}/{total} visuals ready"]
    if real_video:
        parts.append(f"{real_video} topic-matched B-roll")
    if real_image:
        parts.append(f"{real_image} real stills")
    if ai:
        parts.append(f"{ai} AI")
    if user:
        parts.append(f"{user} user media")
    retries = sum(scene.retry_count for scene in project.scenes)
    if retries:
        parts.append(f"{retries} regeneration(s)")
    return " • ".join(parts)


def _save_current_project(window) -> None:
    project = getattr(window, "current_project", None)
    if not project or not project.output_dir:
        return
    project.save(Path(project.output_dir) / "project.json")


def _replace_visual(window, scene: Scene) -> None:
    filename, _ = QFileDialog.getOpenFileName(
        window,
        f"Replace visual for scene {scene.index}",
        str(Path.home()),
        "Media (*.png *.jpg *.jpeg *.webp *.mp4 *.webm *.mov *.mkv *.m4v);;All files (*.*)",
    )
    if not filename:
        return
    source = Path(filename)
    out_dir = Path(window.current_project.output_dir)
    suffix = source.suffix.lower() or ".bin"
    target = out_dir / f"scene_{scene.index:03d}_user{suffix}"
    if source.resolve() != target.resolve():
        shutil.copy2(source, target)
    scene.image_path = str(target)
    scene.media_type = "video" if _is_video_path(target) else "image"
    scene.source_type = "User Video" if scene.media_type == "video" else "User Image"
    scene.source_url = ""
    scene.source_credit = "User supplied"
    scene.source_license = "User supplied"
    scene.source_query = "Scene Editor replacement"
    scene.quality_score = 100
    scene.quality_notes = ["manually replaced in Scene Editor"]
    scene.status = "image-ready"
    _save_current_project(window)
    window._refresh_scenes()


def _edit_narration(window, scene: Scene) -> None:
    text, ok = QInputDialog.getMultiLineText(
        window,
        f"Edit narration — Scene {scene.index}",
        "Narration:",
        scene.narration,
    )
    cleaned = " ".join(text.split()).strip()
    if not ok or not cleaned or cleaned == scene.narration:
        return
    scene.narration = cleaned
    project = window.current_project
    project.script = " ".join(item.narration.strip() for item in project.scenes if item.narration.strip())
    _save_current_project(window)
    window._refresh_scenes()


class EditorRenderThread(QThread):
    progress_changed = Signal(int, str)
    completed = Signal(object)
    failed = Signal(str)

    def __init__(self, settings, project: Project, render_options: dict):
        super().__init__()
        self.settings = settings
        self.project = project
        self.render_options = render_options

    def run(self):
        try:
            project = self.project
            out_dir = Path(project.output_dir)
            work = out_dir / "_editor_voice"
            shutil.rmtree(work, ignore_errors=True)
            work.mkdir(parents=True, exist_ok=True)
            self.progress_changed.emit(8, "Scene Editor • re-performing edited narration")
            engine = self.render_options.get("voice_engine") or getattr(self.settings, "voice_engine", "Kokoro Directed")
            delivery = self.render_options.get("voice_delivery") or getattr(self.settings, "voice_delivery", "Natural Storyteller")
            voice = v070_voice.voice_service_for(self.settings, engine, delivery, False)
            candidate = voice.generate(project, work, progress=self.progress_changed.emit)
            audio = out_dir / "narration.wav"
            shutil.copy2(candidate, audio)
            project.narration_path = str(audio)

            captions = None
            if self.render_options.get("captions", True):
                self.progress_changed.emit(55, "Scene Editor • rebuilding speech-paced captions")
                caption_service = services.CaptionService()
                caption_service._zr_caption_style = self.render_options.get("caption_style", "TikTok Pop")
                caption_service._zr_caption_position = self.render_options.get("caption_position", "Auto Safe")
                caption_service._zr_caption_size = self.render_options.get("caption_size", "Small")
                captions = caption_service.generate_from_scenes(project, out_dir)
                project.captions_path = str(captions)

            self.progress_changed.emit(70, "Scene Editor • re-rendering with existing visuals")
            renderer = services.FFmpegRenderer(self.settings)
            renderer._zr_progress = self.progress_changed.emit
            renderer._zr_caption_style = self.render_options.get("caption_style", "TikTok Pop")
            renderer._zr_caption_filename = Path(captions).name if captions else ""
            renderer._zr_soundtrack_mode = self.render_options.get("soundtrack_mode", "Smart Soundscape")
            renderer._zr_sfx = bool(self.render_options.get("sfx", True))
            renderer._zr_project = project
            renderer._zr_dynamic_visual_pacing = True
            video, burned = renderer.render(
                project,
                audio,
                captions,
                out_dir,
                motion=bool(self.render_options.get("motion", True)),
                transitions=bool(self.render_options.get("transitions", True)),
                caption_position=self.render_options.get("caption_position", "Auto Safe"),
                caption_size=self.render_options.get("caption_size", "Small"),
                transition_style=self.render_options.get("transition_style", "Story Rhythm"),
            )
            project.video_path = str(video)
            project.captions_burned = burned
            project.save(out_dir / "project.json")
            shutil.rmtree(work, ignore_errors=True)
            self.progress_changed.emit(100, "Edited video ready")
            self.completed.emit(project)
        except Exception as exc:
            self.failed.emit(str(exc) or exc.__class__.__name__)


def install() -> None:
    global _INSTALLED
    if _INSTALLED:
        return

    # Pipeline/source integration. v0.7.1 resolves WikimediaImageService at runtime.
    v071_pipeline.WikimediaImageService = WikimediaMediaService
    v071_pipeline._quality_summary = _quality_summary
    services.FFmpegRenderer._render_scene_clips = render_media_scene_clips

    original_pipeline_run = pipeline.Pipeline.run

    def pipeline_run(self, project, options, progress=lambda value, text: None):
        project.web_video_broll = bool(getattr(options, "web_video_broll", True))
        return original_pipeline_run(self, project, options, progress)

    pipeline.Pipeline.run = pipeline_run

    original_sidebar = ui.MainWindow._sidebar
    original_create_page = ui.MainWindow._create_page
    original_options = ui.MainWindow._options
    original_scenes_page = ui.MainWindow._scenes_page

    def sidebar(self):
        frame = original_sidebar(self)
        for label in frame.findChildren(QLabel):
            if label.text().startswith("v0."):
                label.setText("v0.9 EDITOR")
                label.setMaximumWidth(126)
                break
        return frame

    def create_page(self):
        page = original_create_page(self)
        quality = getattr(self, "create_quality_card", None)
        grid = quality.layout() if quality is not None else None
        if grid is not None and hasattr(grid, "addWidget"):
            self.web_video_broll_check = QCheckBox("Topic-matched real B-roll video")
            self.web_video_broll_check.setChecked(True)
            self.web_video_broll_check.setToolTip(
                "Real/Hybrid mode searches Wikimedia Commons video for the exact spoken beat. Weak matches are rejected and fall back to a relevant still instead. Source, credit and license are saved automatically."
            )
            grid.addWidget(self.web_video_broll_check, 17, 0, 1, 2)

            def sync_enabled(value: str):
                self.web_video_broll_check.setEnabled(value in {"Real Web Images", "Hybrid"})

            if hasattr(self, "image_source_box"):
                self.image_source_box.currentTextChanged.connect(sync_enabled)
                sync_enabled(self.image_source_box.currentText())
            quality.adjustSize()
            quality.setMinimumHeight(max(quality.minimumHeight(), quality.sizeHint().height() + 10))
        return page

    def options(self):
        opts = original_options(self)
        opts.web_video_broll = bool(getattr(self, "web_video_broll_check", None) and self.web_video_broll_check.isChecked())
        return opts

    def scenes_page(self):
        page = original_scenes_page(self)
        layout = page.layout()
        bar = ui.Card()
        row = QHBoxLayout(bar)
        row.setContentsMargins(16, 12, 16, 12)
        note = QLabel("Scene Editor • rewrite one line or replace one visual, then re-render without regenerating the whole project.")
        note.setObjectName("Hint")
        note.setWordWrap(True)
        self.editor_render_button = ui.SoftButton("Re-render Edited Project")
        self.editor_render_button.setObjectName("Primary")
        self.editor_render_button.clicked.connect(lambda checked=False: self._rerender_edited_project())
        row.addWidget(note, 1)
        row.addWidget(self.editor_render_button)
        self.editor_progress = QProgressBar()
        self.editor_progress.setRange(0, 100)
        self.editor_progress.setValue(0)
        self.editor_status = QLabel("No pending editor render.")
        self.editor_status.setObjectName("Hint")
        wrapper = QVBoxLayout()
        wrapper.addWidget(bar)
        wrapper.addWidget(self.editor_progress)
        wrapper.addWidget(self.editor_status)
        layout.insertLayout(2, wrapper)
        return page

    def refresh_scenes(self):
        if not hasattr(self, "scene_layout"):
            return
        while self.scene_layout.count() > 1:
            item = self.scene_layout.takeAt(0)
            if item.widget():
                item.widget().deleteLater()
        if not self.current_project or not self.current_project.scenes:
            empty = QLabel("Generate a reel first. Your scenes will appear here.")
            empty.setObjectName("Subtitle")
            self.scene_layout.insertWidget(0, empty)
            return

        portrait = self.current_project.format == "9:16"
        for scene in self.current_project.scenes:
            card = ui.Card()
            row = QHBoxLayout(card)
            row.setContentsMargins(16, 16, 16, 16)
            row.setSpacing(16)
            preview = QLabel()
            preview.setFixedSize(126 if portrait else 180, 180 if portrait else 102)
            preview.setAlignment(Qt.AlignCenter)
            preview.setStyleSheet(f"background:{ui.SURFACE_2}; border-radius:10px;")
            if _video_scene(scene):
                preview.setText("VIDEO\nB-ROLL")
                preview.setStyleSheet(
                    f"background:{ui.SURFACE_2}; border-radius:10px; color:{ui.ACCENT}; font-weight:800;"
                )
            elif scene.image_path and Path(scene.image_path).exists():
                pix = QPixmap(scene.image_path)
                if not pix.isNull():
                    preview.setPixmap(pix.scaled(preview.size(), Qt.KeepAspectRatioByExpanding, Qt.SmoothTransformation))

            text = QVBoxLayout()
            quality = f"Q{scene.quality_score}" if scene.quality_score else "Q—"
            title = QLabel(
                f"Scene {scene.index:02d} • {scene.duration:.1f}s • {scene.shot_role or 'Shot'} • {quality} • {scene.source_type}"
            )
            title.setObjectName("Section")
            narration = QLabel(scene.narration)
            narration.setWordWrap(True)
            meta_parts = []
            if scene.motion_style:
                meta_parts.append(f"Motion: {scene.motion_style}")
            if scene.transition_to_next:
                meta_parts.append(f"Next: {scene.transition_to_next}")
            if scene.source_license and scene.source_type.startswith("Wikimedia"):
                meta_parts.append(f"License: {scene.source_license}")
            if scene.quality_notes:
                meta_parts.append("Quality: " + ", ".join(scene.quality_notes[:2]))
            meta = QLabel(" • ".join(meta_parts))
            meta.setWordWrap(True)
            meta.setObjectName("Hint")
            actions = QHBoxLayout()
            edit = ui.SoftButton("Edit Narration")
            replace = ui.SoftButton("Replace Visual")
            edit.clicked.connect(lambda checked=False, s=scene: _edit_narration(self, s))
            replace.clicked.connect(lambda checked=False, s=scene: _replace_visual(self, s))
            actions.addWidget(edit)
            actions.addWidget(replace)
            actions.addStretch(1)
            text.addWidget(title)
            text.addWidget(narration)
            if meta_parts:
                text.addWidget(meta)
            text.addLayout(actions)
            text.addStretch(1)
            row.addWidget(preview)
            row.addLayout(text, 1)
            self.scene_layout.insertWidget(self.scene_layout.count() - 1, card)

    def rerender_edited_project(self):
        project = getattr(self, "current_project", None)
        if not project or not project.output_dir or not project.scenes:
            QMessageBox.information(self, "ZeroReels", "Generate a project first, then edit its scenes.")
            return
        worker = getattr(self, "editor_worker", None)
        if worker is not None and worker.isRunning():
            return
        render_options = {
            "voice_engine": getattr(self, "voice_engine_box", None).currentText() if hasattr(self, "voice_engine_box") else self.settings.voice_engine,
            "voice_delivery": getattr(self, "voice_delivery_box", None).currentText() if hasattr(self, "voice_delivery_box") else self.settings.voice_delivery,
            "captions": self.captions.isChecked() if hasattr(self, "captions") else True,
            "caption_style": self.caption_style_box.currentText() if hasattr(self, "caption_style_box") else "TikTok Pop",
            "caption_position": self.caption_position_box.currentText() if hasattr(self, "caption_position_box") else "Auto Safe",
            "caption_size": self.caption_size_box.currentText() if hasattr(self, "caption_size_box") else "Small",
            "transition_style": self.transition_style_box.currentText() if hasattr(self, "transition_style_box") else "Story Rhythm",
            "soundtrack_mode": self.soundtrack_box.currentText() if hasattr(self, "soundtrack_box") else "Smart Soundscape",
            "sfx": self.sfx_check.isChecked() if hasattr(self, "sfx_check") else True,
            "motion": self.motion.isChecked() if hasattr(self, "motion") else True,
            "transitions": self.transitions.isChecked() if hasattr(self, "transitions") else True,
        }
        self.editor_render_button.setEnabled(False)
        self.editor_progress.setValue(1)
        self.editor_status.setText("Starting editor re-render...")
        self.editor_worker = EditorRenderThread(self.settings, project, render_options)
        self.editor_worker.progress_changed.connect(
            lambda value, text: (self.editor_progress.setValue(value), self.editor_status.setText(text))
        )

        def done(updated):
            self.current_project = updated
            self.editor_render_button.setEnabled(True)
            self.editor_progress.setValue(100)
            self.editor_status.setText("Edited video ready. Use Play Output from Create.")
            self.open_output.setEnabled(True)
            self._refresh_scenes()

        def failed(message):
            self.editor_render_button.setEnabled(True)
            self.editor_progress.setValue(0)
            self.editor_status.setText("Editor render failed — " + message)
            QMessageBox.critical(self, "ZeroReels Scene Editor", message)

        self.editor_worker.completed.connect(done)
        self.editor_worker.failed.connect(failed)
        self.editor_worker.start()

    ui.MainWindow._sidebar = sidebar
    ui.MainWindow._create_page = create_page
    ui.MainWindow._options = options
    ui.MainWindow._scenes_page = scenes_page
    ui.MainWindow._refresh_scenes = refresh_scenes
    ui.MainWindow._rerender_edited_project = rerender_edited_project
    _INSTALLED = True
