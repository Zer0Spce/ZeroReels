from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

from zeroreels import v070_voice, v075_voice_fix
from zeroreels.models import Project, Scene


def test_chatterbox_runner_adapts_to_installed_api():
    source = v075_voice_fix.CHATTERBOX_RUNNER
    assert "inspect.signature" in source
    assert "if 'nano' in params" in source
    assert "Turbo compatibility" in source
    assert "soundfile" in source
    assert "torchaudio" not in source


def test_f5_runner_bypasses_torchcodec_audio_loading():
    source = v075_voice_fix.F5_RUNNER
    assert "torchaudio.load=_soundfile_load" in source
    assert "torchaudio.save=_soundfile_save" in source
    assert "reference transcript" in source.lower()
    assert "from f5_tts.api import F5TTS" in source


def test_known_optional_voice_failures_get_clear_summaries():
    assert "TorchCodec" in v075_voice_fix._failure_summary(
        "F5-TTS Studio", "OSError: Could not load libtorchcodec_core5.dll"
    )
    assert "older" in v075_voice_fix._failure_summary(
        "Chatterbox Nano", "TypeError: from_pretrained() got an unexpected keyword argument 'nano'"
    )


def test_f5_missing_reference_transcript_falls_back_to_kokoro(tmp_path, monkeypatch):
    python_exe = tmp_path / "python.exe"
    python_exe.write_bytes(b"stub")
    ref = tmp_path / "voice.wav"
    ref.write_bytes(b"RIFFstub")
    settings = SimpleNamespace(
        chatterbox_python="",
        f5_python=str(python_exe),
        natural_voice_ref=str(ref),
        natural_voice_ref_text="",
    )
    service = v070_voice.ExternalNaturalVoiceService(settings, "F5-TTS Studio", "Serious Documentary")
    project = Project(
        topic="test",
        scenes=[Scene(1, "A short line.", "visual", 3.0, shot_role="Hook")],
    )
    target = tmp_path / "narration.wav"

    def fake_kokoro(self, project, out_dir, progress=None):
        target.write_bytes(b"RIFF" + b"0" * 2000)
        project.voice_engine_used = "Kokoro Directed"
        return target

    monkeypatch.setattr(v070_voice.KokoroDirectedVoiceService, "generate", fake_kokoro)
    result = v075_voice_fix.compatible_external_generate(service, project, tmp_path)

    assert result == target
    assert project.voice_engine_used == "Kokoro Directed (fallback from F5-TTS Studio)"


def test_external_engine_process_failure_is_nonfatal_when_kokoro_is_available(tmp_path, monkeypatch):
    python_exe = tmp_path / "python.exe"
    python_exe.write_bytes(b"stub")
    ref = tmp_path / "voice.wav"
    ref.write_bytes(b"RIFFstub")
    settings = SimpleNamespace(
        chatterbox_python=str(python_exe),
        f5_python="",
        natural_voice_ref=str(ref),
        natural_voice_ref_text="reference words",
    )
    service = v070_voice.ExternalNaturalVoiceService(settings, "Chatterbox Nano", "Natural Storyteller")
    project = Project(
        topic="test",
        scenes=[Scene(1, "A short line.", "visual", 3.0, shot_role="Hook")],
    )
    target = tmp_path / "narration.wav"

    class FailedProcess:
        returncode = 1
        stdout = ""
        stderr = "TypeError: got an unexpected keyword argument 'nano'"

    monkeypatch.setattr(v075_voice_fix, "run_hidden", lambda *a, **k: FailedProcess())

    def fake_kokoro(self, project, out_dir, progress=None):
        target.write_bytes(b"RIFF" + b"0" * 2000)
        return target

    monkeypatch.setattr(v070_voice.KokoroDirectedVoiceService, "generate", fake_kokoro)
    result = v075_voice_fix.compatible_external_generate(service, project, tmp_path)

    assert result == target
    assert project.voice_engine_used == "Kokoro Directed (fallback from Chatterbox Nano)"
