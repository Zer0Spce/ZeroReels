from types import SimpleNamespace

from zeroreels.models import Project
from zeroreels import v080_script
from zeroreels.v082_natural_voice import (
    FAST_CLONE_ENGINE,
    FAST_CLONE_RUNNER,
    FastCloneVoiceService,
    _ear_pass,
    robotic_score,
    voice_service_for_v082,
)


def test_robotic_score_penalizes_canned_ai_cadence():
    robotic = (
        "Imagine this. Here's the thing. The truth is, it wasn't just a network, but a revolution. "
        "Did you know that everything changed? What makes this story so incredible? Let that sink in."
    )
    natural = (
        "At 8:12 that morning, the network went dark. Phones still worked for a while. "
        "Then card payments started failing. By lunch, people were lining up for cash. "
        "The strange part was how quickly normal routines stopped feeling normal."
    )
    bad_score, bad_flags = robotic_score(robotic)
    good_score, _ = robotic_score(natural)
    assert bad_score > good_score
    assert "canned phrase" in bad_flags


def test_ear_pass_accepts_more_spoken_rewrite(monkeypatch):
    project = Project(topic="What if the internet disappeared?", style="TikTok Story")
    source = [
        "Imagine this. The internet suddenly disappears.",
        "The reality is, payment systems would begin failing almost immediately.",
    ]

    def fake_json_call(*args, **kwargs):
        return {
            "scenes": [
                {"narration": "The internet goes dark, and the first thing you notice is how ordinary everything still looks."},
                {"narration": "Then payments start failing, because so much of that system quietly depends on being online."},
            ]
        }

    monkeypatch.setattr(v080_script, "_json_call", fake_json_call)
    service = SimpleNamespace()
    result = _ear_pass(service, project, "qwen3:8b", source)
    assert result != source
    assert "Imagine this" not in " ".join(result)


def test_fast_clone_engine_uses_reference_audio_and_cuda_auto():
    assert "audio_prompt_path=a.ref" in FAST_CLONE_RUNNER
    assert "torch.cuda.is_available()" in FAST_CLONE_RUNNER
    assert "ChatterboxTurboTTS.from_pretrained" in FAST_CLONE_RUNNER


def test_fast_clone_voice_service_selection():
    settings = SimpleNamespace()
    service = voice_service_for_v082(settings, FAST_CLONE_ENGINE, "Natural Storyteller", False)
    assert isinstance(service, FastCloneVoiceService)
    assert service.engine == FAST_CLONE_ENGINE
