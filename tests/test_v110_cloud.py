from __future__ import annotations

from pathlib import Path

from zeroreels.models import Project
from zeroreels import v110_cloud


def test_eleven_v4_keeps_native_audio_tags():
    value = "[curious] This changed everything. [gasps] Nobody expected it."
    assert v110_cloud._eleven_text_for_model(value, "eleven_v4") == value


def test_flash_translates_pauses_and_removes_emotion_tags():
    value = "[curious] This changed everything. [pause] Then it got worse. [long pause] Finally, silence."
    rendered = v110_cloud._eleven_text_for_model(value, "eleven_flash_v2_5")
    assert "[curious]" not in rendered
    assert "[pause]" not in rendered
    assert '<break time="0.6s" />' in rendered
    assert '<break time="1.2s" />' in rendered
    assert "This changed everything" in rendered


def test_performance_validation_ignores_tags_but_not_word_changes():
    clean = "Nobody expected the lights to fail."
    tagged = "[whispers] Nobody expected the lights to fail. [sighs]"
    changed = "[whispers] Nobody expected all the lights to fail."
    assert v110_cloud._tagless_words(clean) == v110_cloud._tagless_words(tagged)
    assert v110_cloud._tagless_words(clean) != v110_cloud._tagless_words(changed)


def test_custom_script_preserves_words_and_builds_scene_plan():
    project = Project(
        topic="A city-wide blackout",
        target_seconds=45,
        custom_script=(
            "The first substation failed without warning. The outage jumped across the city. "
            "Traffic lights died and trains stopped. Hospitals switched to backup power. "
            "By sunrise, crews had isolated the fault. The grid came back section by section."
        ),
        script_mode="Custom Script",
    )
    script, scenes = v110_cloud._custom_script(project, 6)
    assert script == project.custom_script
    assert len(scenes) == 6
    assert scenes[0].shot_role == "Hook"
    assert scenes[-1].shot_role == "Landing"
    assert all(scene.source_query.startswith("Planned B-roll: ") for scene in scenes)


def test_chatgpt_writer_is_single_pass_and_produces_broll_plan(monkeypatch):
    project = Project(topic="Origins of Area 51", target_seconds=30)
    project.script_mode = "ChatGPT Script"

    def fake_json(prompt, schema, name, **kwargs):
        assert "There is no later Story Director pass" in prompt
        assert name == "zeroreels_script"
        return {
            "title": "The Real Beginning of Area 51",
            "scenes": [
                {
                    "narration": f"Beat {i + 1} moves the story forward with a concrete detail.",
                    "image_prompt": f"Archival desert aviation scene {i + 1}",
                    "broll_query": f"Area 51 aircraft {i + 1}",
                    "shot_role": "Hook" if i == 0 else ("Landing" if i == 4 else "Action"),
                }
                for i in range(5)
            ],
        }

    monkeypatch.setattr(v110_cloud, "_openai_json", fake_json)
    script, scenes = v110_cloud.chatgpt_generate(object(), project, 5)
    assert len(scenes) == 5
    assert project.title == "The Real Beginning of Area 51"
    assert project.script == script
    assert all(scene.source_query.startswith("Planned B-roll: Area 51 aircraft") for scene in scenes)
    assert "ChatGPT/OpenAI direct writer" in project.script_quality_summary


def test_openai_image_service_writes_png(monkeypatch, tmp_path: Path):
    project = Project(topic="Test")
    _, scenes = v110_cloud._custom_script(
        Project(topic="Test", custom_script="One visual beat. Another visual beat. A final visual beat.", script_mode="Custom Script"),
        3,
    )
    scene = scenes[0]
    monkeypatch.setattr(v110_cloud, "_openai_headers", lambda key=None: {"Authorization": "Bearer test"})
    monkeypatch.setattr(
        v110_cloud,
        "_http_json",
        lambda *args, **kwargs: {"data": [{"b64_json": "iVBORw0KGgoAAAANSUhEUgAAAAEAAAAB"}]},
    )
    target = v110_cloud.OpenAIImageService(object()).generate(scene, tmp_path, "9:16")
    assert target.name.endswith("_openai.png")
    assert target.exists()
    assert scene.source_type == "OpenAI Image"
