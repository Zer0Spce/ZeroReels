from __future__ import annotations

from dataclasses import replace
from pathlib import Path

from . import pipeline, ui, v071_pipeline, v090_editor


_INSTALLED = False
_FORCE_VIDEO_ONLY = False
_PREVIOUS_PIPELINE_RUN = None
_PREVIOUS_CREATE_PAGE = None
_PREVIOUS_SIDEBAR = None
_ORIGINAL_HYBRID_PREFERS_WEB = None
_ORIGINAL_VIDEO_QUERIES = None


def _clean(text: str) -> str:
    return " ".join((text or "").split()).strip()


def smart_video_queries(project, scene) -> list[str]:
    """Prefer the writer-provided literal B-roll query, then use v0.9 fallbacks."""
    planned = _clean(getattr(scene, "source_query", ""))
    if planned.lower().startswith("planned b-roll:"):
        planned = _clean(planned.split(":", 1)[1])
    else:
        planned = ""
    base = _ORIGINAL_VIDEO_QUERIES(project, scene)
    candidates = ([planned] if planned else []) + list(base)
    unique: list[str] = []
    seen: set[str] = set()
    for value in candidates:
        value = _clean(value)
        key = value.casefold()
        if value and key not in seen:
            seen.add(key)
            unique.append(value)
    return unique


def _motion_slot(scene, index: int) -> bool:
    role = (getattr(scene, "shot_role", "") or "").casefold()
    if role in {"action", "escalation", "peak"}:
        return True
    return role in {"establishing", "aftermath"} and index % 3 == 0


def smart_hybrid_prefers_web(scene, index: int) -> bool:
    if _FORCE_VIDEO_ONLY:
        return _motion_slot(scene, index)
    return _ORIGINAL_HYBRID_PREFERS_WEB(scene, index)


class VideoFirstMediaService(v090_editor.WikimediaMediaService):
    """When AI visuals are primary, only use the web if a real motion clip matches."""

    def generate(self, scene, out_dir: Path, fmt: str) -> Path:
        if _FORCE_VIDEO_ONLY:
            if not self._wants_motion(scene):
                raise RuntimeError("Scene is not scheduled for online motion B-roll")
            result = v090_editor._download_video(self.project, scene, out_dir)
            self.video_count += 1
            return result
        return super().generate(scene, out_dir, fmt)


def video_any_source_pipeline(self, project, options, progress=lambda value, text: None):
    global _FORCE_VIDEO_ONLY
    force = (
        bool(getattr(options, "web_video_broll", True))
        and not bool(getattr(options, "mock_mode", False))
        and getattr(options, "image_source_mode", "AI Generated") == "AI Generated"
    )
    if not force:
        return _PREVIOUS_PIPELINE_RUN(self, project, options, progress)

    original_mode = options.image_source_mode
    hybrid_options = replace(options, image_source_mode="Hybrid")
    _FORCE_VIDEO_ONLY = True
    try:
        progress(34, "Online B-roll • AI visuals stay primary; searching licensed motion clips for key beats")
        result = _PREVIOUS_PIPELINE_RUN(self, project, hybrid_options, progress)
        result.image_source_mode = original_mode
        if result.output_dir:
            result.save(Path(result.output_dir) / "project.json")
        return result
    finally:
        _FORCE_VIDEO_ONLY = False


def sidebar_v100(self):
    frame = _PREVIOUS_SIDEBAR(self)
    try:
        from PySide6.QtWidgets import QLabel
        for label in frame.findChildren(QLabel):
            if label.text().startswith("v0."):
                label.setText("v0.10 VIDEO")
                label.setMaximumWidth(118)
                break
    except Exception:
        pass
    return frame


def create_page_v100(self):
    page = _PREVIOUS_CREATE_PAGE(self)
    check = getattr(self, "web_video_broll_check", None)
    if check is not None:
        check.setText("Online motion B-roll (auto)")
        check.setEnabled(True)
        check.setToolTip(
            "Searches license-traceable Wikimedia Commons video for key spoken beats and stitches matching clips into the reel. "
            "Weak matches fall back to the selected image source."
        )
        box = getattr(self, "image_source_box", None)
        if box is not None:
            box.currentTextChanged.connect(lambda _value, c=check: c.setEnabled(True))
    return page


def install() -> None:
    global _INSTALLED, _PREVIOUS_PIPELINE_RUN, _PREVIOUS_CREATE_PAGE, _PREVIOUS_SIDEBAR
    global _ORIGINAL_HYBRID_PREFERS_WEB, _ORIGINAL_VIDEO_QUERIES
    if _INSTALLED:
        return

    _PREVIOUS_PIPELINE_RUN = pipeline.Pipeline.run
    _PREVIOUS_CREATE_PAGE = ui.MainWindow._create_page
    _PREVIOUS_SIDEBAR = ui.MainWindow._sidebar
    _ORIGINAL_HYBRID_PREFERS_WEB = v071_pipeline.hybrid_prefers_web
    _ORIGINAL_VIDEO_QUERIES = v090_editor._video_queries

    v090_editor._video_queries = smart_video_queries
    v071_pipeline.hybrid_prefers_web = smart_hybrid_prefers_web
    v071_pipeline.WikimediaImageService = VideoFirstMediaService
    pipeline.Pipeline.run = video_any_source_pipeline
    ui.MainWindow._create_page = create_page_v100
    ui.MainWindow._sidebar = sidebar_v100
    _INSTALLED = True
