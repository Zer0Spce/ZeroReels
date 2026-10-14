from zeroreels.config import Settings
from zeroreels.models import Project, Scene
from zeroreels.services import CaptionService, FFmpegRenderer, MockImageService, MockVoiceService, ComfyImageService
from zeroreels import quality_services, renderer_fix


def _mock_project(tmp_path):
    project = Project(topic="A small quality test", target_seconds=6, format="1:1")
    project.scenes = [
        Scene(1, "A quiet beginning, with one clear idea.", "cinematic room [ZR-SEED=12345]", 2.0),
        Scene(2, "Then the story changes direction naturally.", "same room, new angle [ZR-SEED=12345]", 2.0),
        Scene(3, "Finally, it lands on a simple ending.", "same room, final angle [ZR-SEED=12345]", 2.0),
    ]
    for scene in project.scenes:
        scene.image_path = str(MockImageService().generate(scene, tmp_path, project.format))
    return project


def test_caption_groups_prefer_phrase_breaks():
    groups = quality_services._caption_groups("A quiet beginning, with one clear idea. Then everything changes.")
    rendered = [" ".join(group) for group in groups]
    assert rendered[0].endswith(",") or rendered[0].endswith("idea.")
    assert all(len(group) <= 6 for group in groups)


def test_comfy_workflow_reuses_explicit_seed(monkeypatch):
    monkeypatch.setattr(ComfyImageService, "_workflow", quality_services._quality_workflow)
    service = ComfyImageService(Settings())
    workflow_a = service._workflow("same person, close shot [ZR-SEED=424242]", "1:1")
    workflow_b = service._workflow("same person, wide shot [ZR-SEED=424242]", "1:1")
    assert workflow_a["7"]["inputs"]["noise_seed"] == 424242
    assert workflow_b["7"]["inputs"]["noise_seed"] == 424242
    assert "ZR-SEED" not in workflow_a["4"]["inputs"]["text"]


def test_quality_render_creates_mp4_with_bottom_small_captions(tmp_path, monkeypatch):
    monkeypatch.setattr(CaptionService, "generate_from_scenes", quality_services._human_captions)
    monkeypatch.setattr(FFmpegRenderer, "_caption_filter", quality_services._caption_filter)
    monkeypatch.setattr(FFmpegRenderer, "_scene_filter", quality_services._scene_filter)
    monkeypatch.setattr(FFmpegRenderer, "_transition_config", quality_services._transition_config, raising=False)
    monkeypatch.setattr(FFmpegRenderer, "_render_scene_clips", quality_services._render_scene_clips)
    monkeypatch.setattr(FFmpegRenderer, "_combine_filter", renderer_fix._combine_filter_cfr)
    monkeypatch.setattr(FFmpegRenderer, "render", quality_services._render)

    project = _mock_project(tmp_path)
    audio = MockVoiceService().generate(project, tmp_path)
    captions = CaptionService().generate_from_scenes(project, tmp_path)
    video, burned = FFmpegRenderer(Settings()).render(
        project,
        audio,
        captions,
        tmp_path,
        motion=True,
        transitions=True,
        caption_position="Bottom",
        caption_size="Small",
        transition_style="Natural Crossfade",
    )
    assert video.exists()
    assert video.stat().st_size > 10_000
    assert isinstance(burned, bool)
