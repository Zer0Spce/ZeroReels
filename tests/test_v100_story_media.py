from __future__ import annotations

from zeroreels.models import GenerationOptions, Project, Scene
from zeroreels import v100_story_media


def test_rewrite_guard_rejects_new_numbers(monkeypatch):
    monkeypatch.setattr(v100_story_media.v080_script, "_hook_ok", lambda text: True)
    monkeypatch.setattr(v100_story_media.v080_script, "_word_count", lambda text: len(text.split()))
    monkeypatch.setattr(v100_story_media.v080_script, "_script_problems", lambda texts, target: [])
    original = ["Apollo landed in 1969 " + "word " * 60]
    candidate = ["Apollo landed in 1970 " + "word " * 60]
    assert not v100_story_media._rewrite_is_safe(original, candidate, 65)


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


def test_story_director_restores_shot_roles(monkeypatch):
    scenes = [
        Scene(index=1, narration="A hook with a clear event.", image_prompt="event"),
        Scene(index=2, narration="Context follows.", image_prompt="context"),
        Scene(index=3, narration="The final consequence lands.", image_prompt="consequence"),
    ]

    def fake_generate(self, project, scene_count):
        return " ".join(scene.narration for scene in scenes), scenes

    monkeypatch.setattr(v100_story_media, "_PREVIOUS_SCRIPT_GENERATE", fake_generate)
    service = type("Service", (), {"settings": object()})()
    project = Project(topic="Test", script_mode="Custom Script", web_video_broll=False)
    _, result = v100_story_media.story_director_v3(service, project, 3)
    assert result[0].shot_role == "Hook"
    assert result[-1].shot_role == "Landing"
