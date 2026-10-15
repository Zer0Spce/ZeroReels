from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

from zeroreels.models import GenerationOptions, Project, Scene
from zeroreels import v090_editor


def test_generation_options_enable_motion_broll_by_default():
    assert GenerationOptions().web_video_broll is True


def test_video_path_detection():
    assert v090_editor._is_video_path("clip.webm")
    assert v090_editor._is_video_path("clip.MP4")
    assert not v090_editor._is_video_path("still.jpg")


def test_video_queries_start_from_spoken_beat_then_broaden():
    project = Project(topic="Apollo 11", research_context="Apollo 11: Moon landing mission")
    scene = Scene(index=1, narration="The Saturn V lifts off from Cape Kennedy.", image_prompt="rocket launch", shot_role="Action")
    queries = v090_editor._video_queries(project, scene)
    assert queries
    assert "Apollo 11" in queries[0]
    assert any("Saturn" in query or "lifts" in query for query in queries[:3])
    assert queries[-1] == "Apollo 11"


def test_video_search_filters_non_video_results_and_keeps_relevant_video(monkeypatch):
    project = Project(topic="Apollo 11", research_context="Apollo 11: Moon landing mission")
    scene = Scene(index=1, narration="The Saturn V lifts off from Cape Kennedy.", image_prompt="launch", shot_role="Action")

    def fake_json(url, timeout=0):
        assert "filetype%3Avideo" in url
        return {
            "query": {
                "pages": {
                    "1": {
                        "index": 1,
                        "title": "File:Apollo still.jpg",
                        "imageinfo": [{"mime": "image/jpeg", "url": "https://x/still.jpg"}],
                    },
                    "2": {
                        "index": 2,
                        "title": "File:Apollo 11 Saturn V launch.webm",
                        "imageinfo": [{
                            "mime": "video/webm",
                            "url": "https://x/launch.webm",
                            "descriptionurl": "https://commons.wikimedia.org/wiki/File:Apollo_launch.webm",
                            "size": 12000000,
                            "extmetadata": {"LicenseShortName": {"value": "Public domain"}},
                        }],
                    },
                }
            }
        }

    monkeypatch.setattr(v090_editor.v071_web_media, "_json", fake_json)
    page, query = v090_editor._video_search(project, scene)
    assert page is not None
    assert page["title"].endswith("launch.webm")
    assert "Apollo" in query


def test_video_search_rejects_unrelated_video(monkeypatch):
    project = Project(topic="Apollo 11", research_context="Apollo 11: Moon landing mission")
    scene = Scene(index=1, narration="The Saturn V lifts off from Cape Kennedy.", image_prompt="launch", shot_role="Action")

    def fake_json(url, timeout=0):
        return {
            "query": {
                "pages": {
                    "9": {
                        "index": 1,
                        "title": "File:Random tropical fish swimming.webm",
                        "imageinfo": [{
                            "mime": "video/webm",
                            "url": "https://x/fish.webm",
                            "size": 4000000,
                            "extmetadata": {"ImageDescription": {"value": "Colorful reef fish underwater"}},
                        }],
                    }
                }
            }
        }

    monkeypatch.setattr(v090_editor.v071_web_media, "_json", fake_json)
    page, _ = v090_editor._video_search(project, scene)
    assert page is None


def test_download_video_sets_scene_metadata(tmp_path, monkeypatch):
    project = Project(topic="Test")
    scene = Scene(index=1, narration="A machine starts moving.", image_prompt="machine", shot_role="Action")
    page = {
        "title": "File:Machine.webm",
        "imageinfo": [{
            "mime": "video/webm",
            "url": "https://example.test/machine.webm",
            "descriptionurl": "https://commons.wikimedia.org/wiki/File:Machine.webm",
            "size": 12000,
            "extmetadata": {
                "Artist": {"value": "Test Creator"},
                "LicenseShortName": {"value": "CC BY 4.0"},
            },
        }],
    }
    monkeypatch.setattr(v090_editor, "_video_search", lambda project, scene: (page, "Test machine"))

    class FakeHeaders(dict):
        def get(self, key, default=None):
            return super().get(key, default)

    class FakeResponse:
        headers = FakeHeaders({"Content-Length": "12000"})
        def read(self, amount=-1):
            return b"0" * 12000
        def __enter__(self):
            return self
        def __exit__(self, exc_type, exc, tb):
            return False

    monkeypatch.setattr(v090_editor.urllib.request, "urlopen", lambda request, timeout=0: FakeResponse())
    path = v090_editor._download_video(project, scene, tmp_path)
    assert path.exists()
    assert scene.media_type == "video"
    assert scene.source_type == "Wikimedia Commons Video"
    assert scene.source_license == "CC BY 4.0"
    assert scene.source_query.startswith("Topic-matched video:")


def test_media_renderer_uses_stream_loop_for_video(tmp_path, monkeypatch):
    source = tmp_path / "clip.webm"
    source.write_bytes(b"fake")
    project = Project(topic="Test", format="9:16")
    project.scenes = [
        Scene(index=1, narration="Test", image_prompt="test", duration=2.0, image_path=str(source), media_type="video", source_type="User Video")
    ]
    commands = []

    monkeypatch.setattr(v090_editor.services, "dimensions_for", lambda fmt: (1080, 1920))
    monkeypatch.setattr(v090_editor.v060_render, "_story_transition_plan", lambda self, project, transitions: [])

    class Proc:
        returncode = 0
        stderr = b""

    def fake_run(cmd, **kwargs):
        commands.append(cmd)
        Path(cmd[-1]).write_bytes(b"rendered")
        return Proc()

    monkeypatch.setattr(v090_editor, "run_hidden", fake_run)
    renderer = SimpleNamespace(_ffmpeg=lambda: "ffmpeg", _zr_progress=None)
    clips = v090_editor.render_media_scene_clips(renderer, project, tmp_path, motion=True, transitions=False)
    assert len(clips) == 1
    assert "-stream_loop" in commands[0]
    assert "-loop" not in commands[0]
    assert "-an" in commands[0]


def test_quality_summary_counts_topic_broll():
    project = Project(topic="Test")
    project.scenes = [
        Scene(index=1, narration="a", image_prompt="a", source_type="Wikimedia Commons Video", media_type="video"),
        Scene(index=2, narration="b", image_prompt="b", source_type="Wikimedia Commons"),
        Scene(index=3, narration="c", image_prompt="c", source_type="AI Generated"),
    ]
    text = v090_editor._quality_summary(project)
    assert "1 topic-matched B-roll" in text
    assert "1 real stills" in text
    assert "1 AI" in text
