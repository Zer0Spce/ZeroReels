from zeroreels.config import Settings
from zeroreels.models import Project
from zeroreels.services import (
    CaptionService,
    FFmpegRenderer,
    MockImageService,
    MockScriptService,
    MockVoiceService,
)


def _mock_project(tmp_path):
    project = Project(topic="A tiny test", target_seconds=6, format="1:1")
    project.script, project.scenes = MockScriptService().generate(project, 3)
    for scene in project.scenes:
        path = MockImageService().generate(scene, tmp_path, project.format)
        scene.image_path = str(path)
    return project


def test_mock_components(tmp_path):
    project = _mock_project(tmp_path)
    assert len(project.scenes) == 3
    assert all(scene.image_path for scene in project.scenes)
    audio = MockVoiceService().generate(project, tmp_path)
    captions = CaptionService().generate_from_scenes(project, tmp_path)
    assert audio.exists()
    assert captions.exists()
    assert "-->" in captions.read_text(encoding="utf-8")


def test_mock_render_creates_mp4(tmp_path):
    project = _mock_project(tmp_path)
    audio = MockVoiceService().generate(project, tmp_path)
    captions = CaptionService().generate_from_scenes(project, tmp_path)
    video = FFmpegRenderer(Settings()).render(project, audio, captions, tmp_path, motion=True)
    assert video.exists()
    assert video.stat().st_size > 10_000
