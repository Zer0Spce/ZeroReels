from __future__ import annotations

import json

from zeroreels.config import Settings
from zeroreels.models import Project, Scene
from zeroreels.v071_runtime import rewrite_for_measured_duration_v2


def test_runtime_lock_v2_expands_against_measured_audio(monkeypatch):
    scenes = [
        Scene(i + 1, "This short line explains one clear part of the story now.", "")
        for i in range(8)
    ]
    project = Project(topic="Area 51", target_seconds=60, scenes=scenes)

    # 8 scenes * 15 words = 120 words, matching the measured 40s -> 60s target ratio closely.
    expanded = "This scene now explains the same idea with enough natural spoken detail to hold attention without adding unsupported facts."
    rows = [{"narration": expanded} for _ in scenes]
    monkeypatch.setattr(
        "zeroreels.v071_runtime.services._post_json",
        lambda *args, **kwargs: {"response": json.dumps({"scenes": rows})},
    )

    assert rewrite_for_measured_duration_v2(Settings(), project, 40.0, pass_index=1)
    assert project.runtime_rewrites == 1
    assert all(scene.narration == expanded for scene in project.scenes)


def test_runtime_lock_v2_skips_when_already_close():
    project = Project(
        topic="test",
        target_seconds=60,
        scenes=[Scene(1, "A normal line.", ""), Scene(2, "Another line.", ""), Scene(3, "Final line.", "")],
    )
    assert not rewrite_for_measured_duration_v2(Settings(), project, 58.5)
    assert project.runtime_rewrites == 0
