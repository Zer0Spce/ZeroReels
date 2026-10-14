from zeroreels.models import Project, Scene
from zeroreels.v052_hotfix import _enforce_visual_diversity, _narration_too_repetitive


def test_same_cast_world_uses_fresh_shots_and_seed_family():
    project = Project(topic="Continuity", continuity_mode="Same Cast & World")
    scenes = [
        Scene(1, "First beat moves the story forward.", "same woman in station [ZR-SEED=12345]", reuse_previous_image=False),
        Scene(2, "Second beat adds a new development.", "same woman leaves station [ZR-SEED=12345]", reuse_previous_image=True),
        Scene(3, "Third beat changes the situation again.", "same woman on platform [ZR-SEED=12345]", reuse_previous_image=True),
    ]

    _enforce_visual_diversity(project, scenes)

    assert all(scene.reuse_previous_image is False for scene in scenes)
    seeds = [scene.image_prompt.rsplit("[ZR-SEED=", 1)[1].rstrip("]") for scene in scenes]
    assert len(set(seeds)) == len(seeds)
    assert all("Distinct shot variation:" in scene.image_prompt for scene in scenes)


def test_repetitive_narration_is_detected():
    scenes = [
        Scene(1, "Rain hits the road and she studies the map.", "a"),
        Scene(2, "Rain hits the road while she studies the same map.", "b"),
        Scene(3, "The story finally moves somewhere else entirely.", "c"),
    ]
    assert _narration_too_repetitive(scenes) is True


def test_distinct_narration_passes():
    scenes = [
        Scene(1, "A storm forces the pilot to change course.", "a"),
        Scene(2, "Hours later, the radio signal begins to fade.", "b"),
        Scene(3, "The search expands across a much wider area.", "c"),
    ]
    assert _narration_too_repetitive(scenes) is False
