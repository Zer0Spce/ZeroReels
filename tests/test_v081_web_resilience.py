from pathlib import Path

from zeroreels.models import Project, Scene
from zeroreels import v081_web_fix as fix


def test_hypothetical_topic_reduces_to_real_subject():
    assert fix.topic_core("What If the Internet Suddenly Disappeared?") == "Internet"
    assert fix.topic_core("What if gravity vanished?") == "gravity"


def test_irrelevant_research_page_cannot_replace_user_subject():
    project = Project(topic="What If the Internet Suddenly Disappeared?")
    project.research_context = "Internet pornography: unrelated search result about adult websites"
    project.research_source = "https://en.wikipedia.org/wiki/Internet_pornography"
    assert fix.safe_primary_subject(project) == "Internet"


def test_scene_query_drops_research_leak_terms():
    project = Project(topic="What If the Internet Suddenly Disappeared?")
    project.research_context = "Internet pornography: unrelated context"
    project.research_source = "https://en.wikipedia.org/wiki/Internet_pornography"
    scene = Scene(
        index=9,
        narration="Danni's Hard and internet pornography sites would also disappear, along with ordinary websites.",
        image_prompt="network outage",
    )
    queries = fix.safe_build_image_queries(project, scene)
    joined = " | ".join(queries).lower()
    assert "danni" not in joined
    assert "porn" not in joined
    assert any(query.lower() == "internet" for query in queries)
    assert "internet infrastructure" in [query.lower() for query in queries]


def test_research_grounding_prefers_exact_subject_page(monkeypatch):
    def fake_json(url: str, timeout: int = 20):
        if "list=search" in url:
            return {
                "query": {
                    "search": [
                        {"pageid": 1, "title": "Internet", "snippet": "global network"},
                        {"pageid": 2, "title": "Internet pornography", "snippet": "adult material"},
                    ]
                }
            }
        return {
            "query": {
                "pages": {
                    "1": {
                        "title": "Internet",
                        "extract": "The Internet is a global system of interconnected computer networks.",
                        "fullurl": "https://en.wikipedia.org/wiki/Internet",
                    }
                }
            }
        }

    monkeypatch.setattr(fix.web_media, "_json", fake_json)
    context, source = fix.safe_fetch_wikipedia_context("What If the Internet Suddenly Disappeared?")
    assert context.startswith("Internet:")
    assert "pornography" not in context.lower()
    assert source.endswith("/Internet")


def test_real_media_can_reuse_previous_topic_image_instead_of_stopping(tmp_path: Path):
    source = tmp_path / "scene_001_web.jpg"
    source.write_bytes(b"real image bytes")
    project = Project(topic="Internet")
    previous = Scene(index=1, narration="one", image_prompt="one", image_path=str(source))
    previous.source_type = "Wikimedia Commons"
    previous.source_url = "https://commons.wikimedia.org/wiki/File:Internet.jpg"
    previous.source_credit = "Example Author"
    previous.source_license = "CC BY 4.0"
    previous.source_query = "Internet"
    scene = Scene(index=9, narration="nine", image_prompt="nine")
    project.scenes = [previous, scene]

    target = fix._reuse_previous_real_image(project, scene, tmp_path)
    assert target is not None
    assert target.exists()
    assert target.read_bytes() == source.read_bytes()
    assert scene.source_type == "Wikimedia Commons"
    assert "fallback reuse" in scene.source_query.lower()
    assert scene.quality_score == 82
