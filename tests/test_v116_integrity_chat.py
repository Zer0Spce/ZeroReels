from __future__ import annotations

from pathlib import Path

from zeroreels import browser_ai, browser_sessions, v116_integrity_chat
from zeroreels.models import Project, Scene


def test_elevenlabs_full_script_verifier_rejects_first_scene_only():
    full = (
        "[shocked] Area 51 was built for secrets.\n\n[pause]\n\n"
        "Hidden in Nevada, the base became famous.\n\n[pause]\n\n"
        "[serious] The final truth is still classified."
    )
    first_only = "[shocked] Area 51 was built for secrets."
    assert v116_integrity_chat._eleven_script_complete(full, full)
    assert not v116_integrity_chat._eleven_script_complete(full, first_only)


def test_minimum_narration_duration_flags_impossible_short_audio():
    minimum = v116_integrity_chat._minimum_plausible_narration_seconds(150)
    assert minimum == 30.0
    assert 6.8 < minimum


def test_render_clip_integrity_requires_every_scene(tmp_path: Path):
    project = Project(topic="Area 51")
    project.scenes = [
        Scene(1, "One", "One", 3.0),
        Scene(2, "Two", "Two", 3.0),
        Scene(3, "Three", "Three", 3.0),
    ]
    clips = []
    for index in range(3):
        path = tmp_path / f"clip_{index}.mp4"
        path.write_bytes(b"0" * 6000)
        clips.append(path)
    assert v116_integrity_chat._verify_clip_set(project, clips) == clips
    try:
        v116_integrity_chat._verify_clip_set(project, clips[:2])
    except RuntimeError as exc:
        assert "2/3" in str(exc)
    else:
        raise AssertionError("missing scene clip was accepted")


def test_chat_reuse_loads_last_zero_reels_conversation(monkeypatch):
    monkeypatch.setattr(
        browser_sessions,
        "_load_state",
        lambda: {"chatgpt": {"last_chat_url": "https://chatgpt.com/c/reuse-this-chat"}},
    )
    v116_integrity_chat._configure_chat_session(False)
    assert browser_ai._thread.chat_new_requested is False
    assert browser_ai._thread.chat_context_ready is False
    assert browser_ai._thread.chat_url == "https://chatgpt.com/c/reuse-this-chat"


def test_new_chat_option_starts_once_not_per_request(monkeypatch):
    v116_integrity_chat._configure_chat_session(True)

    class Page:
        url = "https://chatgpt.com/"

    class Client:
        def __init__(self):
            self.page = Page()
            self.new_chat_calls = 0

        def open(self):
            return self

        def new_chat(self):
            self.new_chat_calls += 1

        def _ensure_ready(self):
            return None

    client = Client()
    monkeypatch.setattr(v116_integrity_chat, "_remember_chat_url", lambda _client: "")
    v116_integrity_chat._ensure_chat_context(client)
    v116_integrity_chat._ensure_chat_context(client)
    assert client.new_chat_calls == 1


def test_project_persists_new_chat_preference(tmp_path: Path):
    project = Project(topic="Demo", chatgpt_new_chat=True)
    path = tmp_path / "project.json"
    project.save(path)
    loaded = Project.load(path)
    assert loaded.chatgpt_new_chat is True
