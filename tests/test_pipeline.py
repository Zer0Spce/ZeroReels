from pathlib import Path

from zeroreels.config import Settings
from zeroreels.models import GenerationOptions, Project
from zeroreels.services import CaptionService, MockImageService, MockScriptService, MockVoiceService


def test_mock_components(tmp_path):
    project = Project(topic="A tiny test", target_seconds=12)
    project.script, project.scenes = MockScriptService().generate(project, 3)
    assert len(project.scenes) == 3
    for scene in project.scenes:
        path = MockImageService().generate(scene, tmp_path, "9:16")
        scene.image_path = str(path)
        assert path.exists()
    audio = MockVoiceService().generate(project, tmp_path)
    captions = CaptionService().generate_from_scenes(project, tmp_path)
    assert audio.exists()
    assert captions.exists()
    assert "-->" in captions.read_text(encoding="utf-8")
