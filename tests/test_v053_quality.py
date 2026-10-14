from __future__ import annotations

import re

from zeroreels.models import Project, Scene
from zeroreels.v053_quality import _build_scene_prompt, _too_repetitive, STYLE_PROFILES


def test_tiktok_story_profile_exists():
    assert "TikTok Story" in STYLE_PROFILES
    assert "conversational" in STYLE_PROFILES["TikTok Story"].lower()


def test_repetition_guard_catches_near_duplicate_scenes():
    scenes = [
        Scene(1, "The rain hits the street while she studies the map.", "a"),
        Scene(2, "Rain hits the street as she keeps studying the same map.", "b"),
        Scene(3, "A train arrives and changes where she can go next.", "c"),
    ]
    assert _too_repetitive(scenes)


def test_repetition_guard_allows_distinct_story_beats():
    scenes = [
        Scene(1, "Earth stops turning, but everything on the surface still has momentum.", "a"),
        Scene(2, "Near the equator, that sideways speed is enormous, so unsecured objects keep moving.", "b"),
        Scene(3, "The oceans would not calmly stay in place either; water would surge across coastlines.", "c"),
    ]
    assert not _too_repetitive(scenes)


def test_same_cast_world_uses_fresh_seed_family_and_shot_roles():
    project = Project(topic="A traveler follows a strange signal", style="TikTok Story", continuity_mode="Same Cast & World")
    prompts = [
        _build_scene_prompt(project, "cinematic natural light", "woman, short dark hair, yellow coat", "walking through a station", i, 123456)
        for i in range(4)
    ]
    seeds = [int(re.search(r"\[ZR-SEED=(\d+)\]$", prompt).group(1)) for prompt in prompts]
    assert len(set(seeds)) == 4
    assert len(set(prompts)) == 4
    assert all("Fresh composition" in prompt for prompt in prompts)
    assert all("Continuity lock:" in prompt for prompt in prompts)
