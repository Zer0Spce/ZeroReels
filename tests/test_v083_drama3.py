from __future__ import annotations

from io import BytesIO
from pathlib import Path
from types import SimpleNamespace
import json
import wave

from zeroreels.models import Project, Scene
from zeroreels import v083_drama3


def _wav_bytes(seconds: float = 0.25, sample_rate: int = 24000) -> bytes:
    buf = BytesIO()
    with wave.open(buf, "wb") as wav:
        wav.setnchannels(1)
        wav.setsampwidth(2)
        wav.setframerate(sample_rate)
        wav.writeframes(b"\x00\x00" * int(sample_rate * seconds))
    return buf.getvalue()


def test_speech_url_accepts_base_and_full_endpoint():
    assert v083_drama3._speech_url("http://127.0.0.1:8000") == "http://127.0.0.1:8000/v1/audio/speech"
    assert v083_drama3._speech_url("http://host:9000/v1") == "http://host:9000/v1/audio/speech"
    assert v083_drama3._speech_url("http://host:9000/v1/audio/speech") == "http://host:9000/v1/audio/speech"


def test_spoken_chunks_preserve_text_order():
    text = "First sentence is here. Second sentence is a little longer. Third sentence finishes the thought."
    chunks = v083_drama3._spoken_chunks(text, max_chars=50)
    assert len(chunks) >= 2
    assert " ".join(chunks) == text


def test_drama3_service_sends_reference_voice_and_writes_wav(tmp_path, monkeypatch):
    ref = tmp_path / "reference.wav"
    ref.write_bytes(_wav_bytes())
    captured = []

    class FakeResponse:
        def __init__(self):
            self.headers = {"Content-Type": "audio/wav"}

        def read(self):
            return _wav_bytes(0.35)

        def __enter__(self):
            return self

        def __exit__(self, exc_type, exc, tb):
            return False

    def fake_urlopen(request, timeout=0):
        captured.append(json.loads(request.data.decode("utf-8")))
        return FakeResponse()

    monkeypatch.setattr(v083_drama3.urllib.request, "urlopen", fake_urlopen)
    monkeypatch.setattr(
        v083_drama3,
        "load_drama3_settings",
        lambda: v083_drama3.Drama3Settings(endpoint="http://drama.local:8000", model="fishaudio/drama-3"),
    )

    settings = SimpleNamespace(
        natural_voice_ref=str(ref),
        natural_voice_ref_text="This is the reference transcript.",
        chatterbox_python=str(tmp_path / "missing-python.exe"),
        kokoro_model_path="",
        kokoro_voices_path="",
    )
    project = Project(topic="Test", target_seconds=15)
    project.scenes = [Scene(index=1, narration="A natural line for Drama 3.", image_prompt="test")]

    out_dir = tmp_path / "out"
    target = v083_drama3.Drama3VoiceService(settings, "Natural Storyteller").generate(project, out_dir)

    assert target.exists()
    assert target.read_bytes().startswith(b"RIFF")
    assert project.voice_engine_used == v083_drama3.DRAMA3_ENGINE
    assert captured
    payload = captured[0]
    assert payload["model"] == "fishaudio/drama-3"
    assert payload["ref_text"] == "This is the reference transcript."
    assert payload["ref_audio"].startswith("data:audio/wav;base64,")
    assert "A natural line" in payload["input"]


def test_json_audio_response_is_supported():
    audio = _wav_bytes()

    class FakeResponse:
        headers = {"Content-Type": "application/json"}

        def read(self):
            import base64
            return json.dumps({"audio_b64": base64.b64encode(audio).decode("ascii")}).encode("utf-8")

    assert v083_drama3._decode_audio_response(FakeResponse()).startswith(b"RIFF")
