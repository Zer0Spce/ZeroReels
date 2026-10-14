from __future__ import annotations

from pathlib import Path

from zeroreels.models import Project, Scene
from zeroreels.v071_web_media import WikimediaImageService, build_image_query, grounded_topic, hybrid_prefers_web


def test_real_media_query_and_hybrid_roles():
    project = Project(topic="The Story of Area 51")
    scene = Scene(1, "Pilots tested secret aircraft over Groom Lake in Nevada.", "", shot_role="Establishing")
    query = build_image_query(project, scene)
    assert "Area 51" in query
    assert "Pilots" in query or "secret" in query
    assert hybrid_prefers_web(scene, 0)
    scene.shot_role = "Peak"
    assert not hybrid_prefers_web(scene, 0)
    assert "VERIFIED RESEARCH CONTEXT" in grounded_topic("Area 51", "Area 51 is a US Air Force facility.")


def test_wikimedia_service_saves_source_metadata(tmp_path: Path, monkeypatch):
    project = Project(topic="Area 51")
    scene = Scene(1, "Aerial view of Groom Lake and the test facility.", "", shot_role="Establishing")
    service = WikimediaImageService(project)
    service._search = lambda query: [
        {
            "index": 1,
            "title": "File:Groom Lake test site.jpg",
            "imageinfo": [{
                "mime": "image/jpeg",
                "thumburl": "https://upload.wikimedia.org/fake.jpg",
                "descriptionurl": "https://commons.wikimedia.org/wiki/File:Groom_Lake_test_site.jpg",
                "thumbwidth": 1200,
                "thumbheight": 800,
                "extmetadata": {
                    "Artist": {"value": "Public Photographer"},
                    "LicenseShortName": {"value": "CC BY-SA 4.0"},
                },
            }],
        }
    ]

    class Headers:
        @staticmethod
        def get_content_type():
            return "image/jpeg"

    class Response:
        headers = Headers()
        def __enter__(self):
            return self
        def __exit__(self, *args):
            return False
        def read(self, _limit):
            return b"\xff\xd8\xff" + b"x" * 6000

    monkeypatch.setattr("zeroreels.v071_web_media.urllib.request.urlopen", lambda *args, **kwargs: Response())
    path = service.generate(scene, tmp_path, "9:16")
    assert path.exists()
    assert scene.source_type == "Wikimedia Commons"
    assert scene.source_license == "CC BY-SA 4.0"
    assert "commons.wikimedia.org" in scene.source_url
    assert scene.source_credit == "Public Photographer"
