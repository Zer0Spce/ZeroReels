from __future__ import annotations

import re

from zeroreels.models import Project
from zeroreels import v080_pipeline, v080_script
from zeroreels.v080_render import _full_frame_real_filter


def _words(text: str) -> list[str]:
    return re.findall(r"[A-Za-z0-9']+", text)


def test_custom_script_split_preserves_word_order():
    source = (
        "At first, nobody noticed the signal. Then the calls stopped. "
        "By sunrise, every radio in town was silent, and that was when people started leaving. "
        "The strange part is that the power never went out."
    )
    beats = v080_script.split_custom_script(source, 6)
    assert len(beats) == 6
    assert _words(" ".join(beats)) == _words(source)


def test_story_qa_rejects_generic_hook_and_canned_language():
    bad = [
        "Did you know this story changes everything?",
        "But here's the crazy part. Nothing was what it seemed.",
        "In conclusion, the mystery remains unsolved.",
    ]
    problems = v080_script._script_problems(bad, 40)
    assert any("hook" in problem for problem in problems)
    assert any("canned" in problem for problem in problems)


def test_specific_spoken_hook_passes():
    assert v080_script._hook_ok("At twenty-two, his career had already reached the top.")


def test_real_web_filter_is_full_frame_without_blurred_matte():
    vf = _full_frame_real_filter(1080, 1920, 150, True, 0)
    assert "force_original_aspect_ratio=increase" in vf
    assert "crop=1080:1920" in vf
    assert "setsar=1" in vf
    assert "boxblur" not in vf
    assert "overlay=" not in vf
    assert "split=2" not in vf


def test_custom_script_runtime_lock_never_rewrites(monkeypatch):
    called = {"value": False}

    def should_not_run(*args, **kwargs):
        called["value"] = True
        return True

    monkeypatch.setattr(v080_pipeline, "_ORIGINAL_RUNTIME_REWRITE", should_not_run)
    project = Project(topic="Custom", script_mode="Custom Script")
    events = []
    changed = v080_pipeline._runtime_rewrite_with_custom_guard(
        object(), project, 42.0, progress=lambda value, text: events.append((value, text)), pass_index=1
    )
    assert changed is False
    assert called["value"] is False
    assert any("preserving your wording" in text for _, text in events)


def test_mock_custom_script_mode_uses_user_words():
    project = Project(
        topic="My story",
        target_seconds=30,
        script_mode="Custom Script",
        custom_script="The door opened. Nobody moved. A phone rang in the empty room. Then the lights came back.",
    )
    script, scenes = v080_script.mock_story_generate(object(), project, 4)
    assert len(scenes) == 4
    assert _words(script) == _words(project.custom_script)
    assert project.script_quality_summary == "Custom script test mode"


def test_auto_quality_prefers_8b_when_installed(monkeypatch):
    class Settings:
        ollama_model = "qwen3:4b"
        ollama_url = "http://127.0.0.1:11434"

    monkeypatch.setattr(v080_script, "_available_models", lambda settings: {"qwen3:8b", "qwen3:4b"})
    model, mode = v080_script.resolve_writer_model(Settings(), "Auto Quality")
    assert model == "qwen3:8b"
    assert mode == "Quality"
