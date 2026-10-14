from zeroreels.models import Project, Scene


def test_project_round_trip(tmp_path):
    project = Project(topic="Test topic", scenes=[Scene(1, "Narration", "Prompt")])
    path = project.save(tmp_path / "project.json")
    loaded = Project.load(path)
    assert loaded.topic == "Test topic"
    assert len(loaded.scenes) == 1
    assert loaded.scenes[0].image_prompt == "Prompt"
