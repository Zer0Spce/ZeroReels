from zeroreels.models import Project, Scene


def test_project_round_trip(tmp_path):
    project = Project(
        topic="Test topic",
        scenes=[Scene(1, "Narration", "Prompt", audio_path="voice.wav")],
        captions_burned=True,
    )
    path = project.save(tmp_path / "project.json")
    loaded = Project.load(path)
    assert loaded.topic == "Test topic"
    assert len(loaded.scenes) == 1
    assert loaded.scenes[0].image_prompt == "Prompt"
    assert loaded.scenes[0].audio_path == "voice.wav"
    assert loaded.captions_burned is True
