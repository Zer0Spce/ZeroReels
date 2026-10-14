from __future__ import annotations

from pathlib import Path

from PySide6.QtGui import QColor, QImage

from zeroreels import quality_services, v060_guardrails, v060_render
from zeroreels.config import Settings
from zeroreels.models import Project, Scene
from zeroreels.services import CaptionService, FFmpegRenderer, MockImageService, MockVoiceService
from zeroreels.v060_render import _story_transition_plan, professional_captions
from zeroreels.v060_story import quality_retry_prompt, scene_quality_report


def _gradient(path: Path, offset: int = 0) -> None:
    image = QImage(96, 96, QImage.Format_RGB32)
    for y in range(96):
        for x in range(96):
            value = (x * 2 + y + offset) % 256
            image.setPixelColor(x, y, QColor(value, min(255, value + 18), max(0, value - 12)))
    assert image.save(str(path))


def test_quality_guard_rejects_near_duplicate(tmp_path: Path):
    first = tmp_path / "a.png"
    second = tmp_path / "b.png"
    _gradient(first)
    _gradient(second)
    score, notes, accepted = scene_quality_report(second, first)
    assert accepted is False
    assert score < 70
    assert any("near-duplicate" in note for note in notes)


def test_quality_retry_moves_seed_marker_to_end():
    scene = Scene(2, "Narration", "cinematic frame [ZR-SEED=123] extra direction", seed=123)
    prompt = quality_retry_prompt(scene, 1)
    assert prompt.rstrip().endswith(f"[ZR-SEED={scene.seed}]")
    assert scene.seed != 123
    assert "single full-frame" in prompt


def test_professional_captions_write_ass_with_keyword_highlight(tmp_path: Path):
    project = Project(topic="Ocean", format="9:16")
    project.scenes = [Scene(1, "The ocean suddenly rises around the city.", "visual", duration=3.0)]
    service = CaptionService()
    service._zr_caption_style = "TikTok Pop"
    service._zr_caption_position = "Bottom"
    service._zr_caption_size = "Small"
    path = professional_captions(service, project, tmp_path)
    text = path.read_text(encoding="utf-8-sig")
    assert path.name == "captions.ass"
    assert "[V4+ Styles]" in text
    assert "Dialogue:" in text
    assert "&H0045C9F6&" in text
    assert "\\t(0,120" in text


def test_story_rhythm_is_mostly_clean_cuts():
    project = Project(topic="Test", style="TikTok Story")
    project.scenes = [Scene(i + 1, f"Beat {i}", "visual", duration=4.0) for i in range(8)]
    renderer = FFmpegRenderer(Settings())
    renderer._zr_transition_style = "Story Rhythm"
    plan = _story_transition_plan(renderer, project, True)
    cuts = sum(1 for kind, _duration, _label in plan if kind == "cut")
    assert len(plan) == 7
    assert cuts >= 5


def test_mixed_cut_and_crossfade_render_executes(tmp_path: Path, monkeypatch):
    project = Project(topic="Edit test", style="TikTok Story", target_seconds=4, format="1:1")
    project.scenes = [
        Scene(i + 1, f"Distinct narration beat number {i + 1}.", f"visual {i}", duration=1.0, shot_role=("Hook", "Establishing", "Detail", "Landing")[i])
        for i in range(4)
    ]
    image_service = MockImageService()
    for scene in project.scenes:
        scene.image_path = str(image_service.generate(scene, tmp_path, project.format))
    audio = MockVoiceService().generate(project, tmp_path)

    monkeypatch.setattr(FFmpegRenderer, "_render_scene_clips", v060_render.professional_render_scene_clips)
    monkeypatch.setattr(FFmpegRenderer, "_combine_filter", v060_guardrails._combine_filter_cfr)
    monkeypatch.setattr(FFmpegRenderer, "_caption_filter", v060_render.professional_caption_filter)
    monkeypatch.setattr(FFmpegRenderer, "render", quality_services._render)

    renderer = FFmpegRenderer(Settings())
    video, burned = renderer.render(
        project,
        audio,
        None,
        tmp_path,
        motion=True,
        transitions=True,
        caption_position="Bottom",
        caption_size="Small",
        transition_style="Story Rhythm",
    )
    assert video.exists()
    assert video.stat().st_size > 10_000
    assert burned is False
    assert any(scene.transition_to_next != "Clean Cut" for scene in project.scenes[:-1])
    assert any(scene.transition_to_next == "Clean Cut" for scene in project.scenes[:-1])
