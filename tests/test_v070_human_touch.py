from pathlib import Path

from PySide6.QtGui import QColor, QImage

from zeroreels.config import Settings
from zeroreels.models import GenerationOptions, Project, Scene
from zeroreels.services import CaptionService
from zeroreels.v070_pipeline import _planned_scene_count
from zeroreels.v070_render import speech_paced_captions
from zeroreels.v070_voice import apply_scene_timing, directed_script
from zeroreels.v070_visual import composition_signature, visual_qa_v2


def _image(path: Path, offset: int = 0) -> None:
    image = QImage(120, 120, QImage.Format_RGB32)
    for y in range(120):
        for x in range(120):
            value = (x * 2 + y + offset) % 240
            image.setPixelColor(x, y, QColor(value, min(255, value + 10), max(0, value - 8)))
    assert image.save(str(path))


def test_dynamic_visual_pacing_raises_sparse_60_second_reel():
    project = Project(topic="Test", target_seconds=60)
    options = GenerationOptions(scene_count=8, dynamic_visual_pacing=True)
    assert _planned_scene_count(project, options) == 12
    options.dynamic_visual_pacing = False
    assert _planned_scene_count(project, options) == 8


def test_voice_director_keeps_one_continuous_script_and_assigns_exact_duration():
    project = Project(topic="Test", target_seconds=30)
    project.scenes = [
        Scene(1, "The first beat starts immediately.", "a", shot_role="Hook"),
        Scene(2, "Then the consequence becomes clear.", "b", shot_role="Action"),
        Scene(3, "And this is where it finally lands.", "c", shot_role="Landing"),
    ]
    text = directed_script(project, "Natural Storyteller")
    assert "first beat" in text and "finally lands" in text
    apply_scene_timing(project, 28.4, "Natural Storyteller")
    assert abs(sum(scene.duration for scene in project.scenes) - 28.4) < 0.05
    assert project.scenes[-1].duration > 0.8


def test_visual_qa_v2_rejects_duplicate_composition(tmp_path: Path):
    first = tmp_path / "first.png"
    second = tmp_path / "second.png"
    _image(first)
    _image(second)
    previous = Scene(1, "one", "one", image_path=str(first))
    previous.composition_signature = composition_signature(first)
    current = Scene(2, "two", "two", image_path=str(second))
    score, notes, accepted = visual_qa_v2(second, current, Settings(), previous=previous, ocr_guard=False)
    assert accepted is False
    assert score < 70
    assert any("duplicate" in note or "similar" in note for note in notes)


def test_speech_paced_captions_use_short_social_phrases(tmp_path: Path):
    project = Project(topic="Test", format="9:16")
    project.scenes = [
        Scene(1, "If Earth stopped spinning, you would feel it almost immediately.", "visual", duration=4.0, shot_role="Hook")
    ]
    service = CaptionService()
    service._zr_caption_style = "TikTok Pop"
    service._zr_caption_position = "Auto Safe"
    service._zr_caption_size = "Small"
    path = speech_paced_captions(service, project, tmp_path)
    text = path.read_text(encoding="utf-8-sig")
    events = [line for line in text.splitlines() if line.startswith("Dialogue:")]
    assert len(events) >= 2
    assert all(",168,," in line for line in events)
    assert "&H0045C9F6&" in text
