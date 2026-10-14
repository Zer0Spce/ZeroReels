from zeroreels.config import Settings, generation_dimensions_for
from zeroreels.models import Project, Scene
from zeroreels.services import CaptionService, ComfyImageService


def test_flux2_distilled_workflow_matches_official_shape():
    service = ComfyImageService(Settings())
    workflow = service._workflow("test prompt", "9:16")
    assert workflow["1"]["class_type"] == "UNETLoader"
    assert workflow["1"]["inputs"]["unet_name"] == "flux-2-klein-4b.safetensors"
    assert workflow["2"]["inputs"]["type"] == "flux2"
    assert workflow["5"]["class_type"] == "ConditioningZeroOut"
    assert workflow["6"]["inputs"]["cfg"] == 1.0
    assert workflow["9"]["inputs"]["steps"] == 4
    width, height = generation_dimensions_for("9:16")
    assert workflow["10"]["inputs"]["width"] == width
    assert workflow["10"]["inputs"]["height"] == height


def test_captions_follow_scene_durations(tmp_path):
    project = Project(
        topic="Timing",
        scenes=[
            Scene(1, "one two three four five six seven eight", "p", duration=2.0),
            Scene(2, "nine ten eleven", "p", duration=3.0),
        ],
    )
    path = CaptionService().generate_from_scenes(project, tmp_path)
    text = path.read_text(encoding="utf-8")
    assert "00:00:05,000" in text
    assert "one two three four five six seven" in text
