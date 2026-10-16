from __future__ import annotations

from pathlib import Path

from zeroreels.models import Project
from zeroreels import browser_ai, browser_sessions


def test_browser_profiles_are_service_specific():
    chat = browser_sessions.profile_path("chatgpt")
    eleven = browser_sessions.profile_path("elevenlabs")
    assert chat != eleven
    assert chat.name == "chatgpt-chrome"
    assert eleven.name == "elevenlabs-chrome"
    assert chat.parent.name == "browser_profiles"


def test_extract_json_from_fenced_chatgpt_response():
    value = browser_ai._extract_json_object('```json\n{"title":"Demo","scenes":[]}\n```')
    assert value == {"title": "Demo", "scenes": []}


def test_tagless_words_ignore_elevenlabs_performance_tags():
    plain = "The room went silent, and then the door opened."
    tagged = "[whispers] The room went silent, [pause] and then the door opened. [gasps]"
    assert browser_ai._tagless_words(plain) == browser_ai._tagless_words(tagged)


def test_image_info_reads_png_dimensions():
    raw = bytearray(32)
    raw[:8] = b"\x89PNG\r\n\x1a\n"
    raw[16:20] = (1024).to_bytes(4, "big")
    raw[20:24] = (1536).to_bytes(4, "big")
    assert browser_ai._image_info(bytes(raw), "image/png") == (".png", 1024, 1536)


def test_audio_sniffer_supports_browser_download_formats():
    assert browser_ai._audio_ext(b"RIFF" + b"\x00" * 20, "audio/wav") == ".wav"
    assert browser_ai._audio_ext(b"ID3" + b"\x00" * 20, "audio/mpeg") == ".mp3"
    assert browser_ai._audio_ext(b"OggS" + b"\x00" * 20, "audio/ogg") == ".ogg"


def test_custom_script_builds_editor_ready_scenes():
    project = Project(
        topic="Browser workflow",
        target_seconds=30,
        custom_script="One two three four five six seven eight nine ten eleven twelve thirteen fourteen fifteen sixteen seventeen eighteen.",
        script_mode="Custom Script",
    )
    script, scenes = browser_ai.custom_script(project, 3)
    assert script == project.custom_script
    assert len(scenes) == 3
    assert scenes[0].shot_role == "Hook"
    assert scenes[-1].shot_role == "Landing"
    assert all(scene.source_query.startswith("Planned B-roll:") for scene in scenes)


def test_services_point_to_consumer_web_apps():
    assert browser_sessions.SERVICES["chatgpt"].url.startswith("https://chatgpt.com/")
    assert browser_sessions.SERVICES["elevenlabs"].url.startswith("https://elevenlabs.io/app/")
