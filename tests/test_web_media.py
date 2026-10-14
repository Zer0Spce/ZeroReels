from __future__ import annotations

from pathlib import Path

from zeroreels.models import Project, Scene
from zeroreels.v071_web_media import (
    WikimediaImageService,
    build_image_query,
    build_image_queries,
    grounded_topic,
    hybrid_prefers_web,
    primary_subject,
)


def _fake_page(title: str = "File:Derrick Rose.jpg") -> dict:
    return {
        "index": 1,
        "title": title,
        "imageinfo": [{
            "mime": "image/jpeg",
            "thumburl": "https://upload.wikimedia.org/fake.jpg",
            "descriptionurl": "https://commons.wikimedia.org/wiki/File:Derrick_Rose.jpg",
            "thumbwidth": 1200,
            "thumbheight": 1600,
            "extmetadata": {
                "Artist": {"value": "Public Photographer"},
                "LicenseShortName": {"value": "CC BY-SA 4.0"},
            },
        }],
    }


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


def test_research_title_becomes_primary_subject_and_queries_broaden():
    project = Project(topic="The Rise And Fall Of NBA Superstar Derrick Rose")
    project.research_context = "Derrick Rose: Derrick Martell Rose is an American former professional basketball player."
    project.research_source = "https://en.wikipedia.org/wiki/Derrick_Rose"
    scene = Scene(1, "Derrick Rose became the NBA's youngest MVP.", "", shot_role="Hook")

    assert primary_subject(project) == "Derrick Rose"
    queries = build_image_queries(project, scene)
    assert "Derrick Rose" in queries
    assert all(len(query) < 90 for query in queries)
    assert not any("The Rise And Fall Of NBA Superstar Derrick Rose Derrick Rose became" in query for query in queries)


def test_topic_subject_cleans_editorial_sports_prefix_without_research():
    project = Project(topic="The Rise And Fall Of NBA Superstar Derrick Rose")
    assert primary_subject(project) == "Derrick Rose"


def test_wikimedia_service_saves_source_metadata(tmp_path: Path, monkeypatch):
    project = Project(topic="Area 51")
    scene = Scene(1, "Aerial view of Groom Lake and the test facility.", "", shot_role="Establishing")
    service = WikimediaImageService(project)
    service._search = lambda query: [_fake_page("File:Groom Lake test site.jpg")]

    monkeypatch.setattr("zeroreels.v071_web_media.urllib.request.urlopen", lambda *args, **kwargs: Response())
    path = service.generate(scene, tmp_path, "9:16")
    assert path.exists()
    assert scene.source_type == "Wikimedia Commons"
    assert scene.source_license == "CC BY-SA 4.0"
    assert "commons.wikimedia.org" in scene.source_url
    assert scene.source_credit == "Public Photographer"


def test_wikimedia_service_broadens_to_subject_search(tmp_path: Path, monkeypatch):
    project = Project(topic="The Rise And Fall Of NBA Superstar Derrick Rose")
    project.research_context = "Derrick Rose: Derrick Martell Rose is an American former professional basketball player."
    scene = Scene(1, "Derrick Rose became the NBA's youngest MVP.", "", shot_role="Hook")
    service = WikimediaImageService(project)
    calls: list[str] = []

    def fake_search(query: str):
        calls.append(query)
        return [_fake_page()] if query == "Derrick Rose" else []

    service._search = fake_search
    service._category = lambda subject: []
    service._wikipedia_lead = lambda subject: []
    monkeypatch.setattr("zeroreels.v071_web_media.urllib.request.urlopen", lambda *args, **kwargs: Response())

    path = service.generate(scene, tmp_path, "9:16")
    assert path.exists()
    assert calls[-1] == "Derrick Rose"
    assert scene.source_query == "Derrick Rose"


def test_wikimedia_service_uses_category_when_searches_miss(tmp_path: Path, monkeypatch):
    project = Project(topic="The Rise And Fall Of NBA Superstar Derrick Rose")
    scene = Scene(1, "A young Derrick Rose enters the league.", "", shot_role="Hook")
    service = WikimediaImageService(project)
    service._search = lambda query: []
    service._category = lambda subject: [_fake_page()]
    service._wikipedia_lead = lambda subject: []
    monkeypatch.setattr("zeroreels.v071_web_media.urllib.request.urlopen", lambda *args, **kwargs: Response())

    path = service.generate(scene, tmp_path, "9:16")
    assert path.exists()
    assert scene.source_query == "Category:Derrick Rose"
