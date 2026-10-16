from __future__ import annotations

from zeroreels.models import GenerationOptions, Project, Scene
from zeroreels import v100_story_media


def test_story_director_is_removed_from_v010_media_module():
    assert not hasattr(v100_story_media, "story_director_v3")
    assert not hasattr(v100_story_media, "_PREVIOUS_SCRIPT_GENERATE")


def test_planned_broll_query_is_first(monkeypatch):
    monkeypatch.setattr(
        v100_story_media,
        "_ORIGINAL_VIDEO_QUERIES",
        lambda project, scene: ["Apollo 11", "Moon landing"],
    )
    project = Project(topic="Apollo 11")
    scene = Scene(
        index=1,
        narration="The rocket launches.",
        image_prompt="rocket launch",
        source_query="Planned B-roll: Saturn V launch",
    )
    queries = v100_story_media.smart_video_queries(project, scene)
    assert queries[0] == "Saturn V launch"
    assert "Apollo 11" in queries


def test_planned_broll_query_is_deduplicated(monkeypatch):
    monkeypatch.setattr(
        v100_story_media,
        "_ORIGINAL_VIDEO_QUERIES",
        lambda project, scene: ["Saturn V launch", "Apollo 11"],
    )
    scene = Scene(
        index=1,
        narration="The rocket launches.",
        image_prompt="rocket launch",
        source_query="Planned B-roll: Saturn V launch",
    )
    queries = v100_story_media.smart_video_queries(Project(topic="Apollo 11"), scene)
    assert queries.count("Saturn V launch") == 1


def test_force_video_mode_uses_motion_roles(monkeypatch):
    monkeypatch.setattr(v100_story_media, "_FORCE_VIDEO_ONLY", True)
    assert v100_story_media.smart_hybrid_prefers_web(
        Scene(index=1, narration="", image_prompt="", shot_role="Action"), 1
    )
    assert not v100_story_media.smart_hybrid_prefers_web(
        Scene(index=2, narration="", image_prompt="", shot_role="Detail"), 1
    )


def test_ai_generated_pipeline_temporarily_uses_hybrid(monkeypatch):
    seen = {}

    def fake_run(self, project, options, progress):
        seen["mode"] = options.image_source_mode
        return project

    monkeypatch.setattr(v100_story_media, "_PREVIOUS_PIPELINE_RUN", fake_run)
    project = Project(topic="Test")
    options = GenerationOptions(image_source_mode="AI Generated", web_video_broll=True)
    result = v100_story_media.video_any_source_pipeline(None, project, options)
    assert seen["mode"] == "Hybrid"
    assert result.image_source_mode == "AI Generated"
    assert v100_story_media._FORCE_VIDEO_ONLY is False
