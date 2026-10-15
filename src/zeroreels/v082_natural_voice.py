from __future__ import annotations

from collections import Counter
from pathlib import Path
import re
import subprocess

from PySide6.QtWidgets import QLabel

from . import services, ui, v070_pipeline, v070_voice, v071_pipeline, v075_voice_fix, v080_script
from .win_subprocess import run_hidden


FAST_CLONE_ENGINE = "Chatterbox Turbo Fast Clone"

_ROBOTIC_PHRASES = (
    "did you know",
    "imagine this",
    "picture this",
    "you won't believe",
    "you will not believe",
    "this is the story of",
    "but here's the crazy part",
    "but here is the crazy part",
    "here's the thing",
    "here is the thing",
    "the truth is",
    "at its core",
    "in today's world",
    "in today’s world",
    "what makes this so",
    "what makes this story",
    "this raises an important question",
    "it begs the question",
    "let that sink in",
    "the reality is",
    "in conclusion",
    "ultimately, this",
    "not only",
)


def _sentences(text: str) -> list[str]:
    return [s.strip() for s in re.split(r"(?<=[.!?…])\s+", (text or "").strip()) if s.strip()]


def _words(text: str) -> list[str]:
    return re.findall(r"\b[\w'’-]+\b", text or "")


def robotic_score(text: str) -> tuple[int, list[str]]:
    """Cheap local check for common LLM narration cadence. Lower is better."""
    value = " ".join((text or "").split()).strip()
    lower = value.casefold()
    sentences = _sentences(value)
    flags: list[str] = []
    score = 0

    hits = [phrase for phrase in _ROBOTIC_PHRASES if phrase in lower]
    if hits:
        score += min(12, len(hits) * 3)
        flags.append("canned phrase")

    questions = value.count("?")
    if questions > 1:
        score += (questions - 1) * 2
        flags.append("too many rhetorical questions")

    dash_count = value.count("—")
    if dash_count > max(1, len(sentences) // 4):
        score += 2
        flags.append("em-dash cadence")

    long_sentences = sum(1 for sentence in sentences if len(_words(sentence)) > 27)
    if long_sentences:
        score += long_sentences * 2
        flags.append("written-length sentences")

    openings: list[str] = []
    lengths: list[int] = []
    for sentence in sentences:
        words = [w.casefold() for w in _words(sentence)]
        if words:
            openings.append(" ".join(words[:2]))
            lengths.append(len(words))
    if openings and max(Counter(openings).values()) >= 3:
        score += 3
        flags.append("repeated sentence openings")

    # A reel where nearly every sentence lands in the same narrow length band often sounds
    # machine-written even when individual sentences are grammatical.
    if len(lengths) >= 6 and max(lengths) - min(lengths) <= 6:
        score += 2
        flags.append("flat sentence rhythm")

    for pattern in (r"\bnot\s+\w+(?:\s+\w+){0,4},?\s+but\b", r"\bit wasn't just\b", r"\bit was not just\b"):
        count = len(re.findall(pattern, lower))
        if count:
            score += count * 2
            flags.append("symmetrical contrast template")

    return score, list(dict.fromkeys(flags))


def _protected_tokens(text: str) -> set[str]:
    # Preserve explicit numbers and likely proper names through the style-only Ear Pass.
    numbers = set(re.findall(r"\b\d[\d,.:/%-]*\b", text or ""))
    names = set(re.findall(r"\b[A-Z][a-z]+(?:\s+[A-Z][a-z]+){0,2}\b", text or ""))
    stop = {"The", "A", "An", "But", "And", "So", "When", "After", "Before", "For", "Then", "That", "This"}
    return numbers | {name for name in names if name not in stop}


def _ear_pass(service, project, model: str, narrations: list[str]) -> list[str]:
    count = len(narrations)
    if not narrations:
        return narrations
    schema = {
        "type": "object",
        "properties": {
            "scenes": {
                "type": "array",
                "minItems": count,
                "maxItems": count,
                "items": {
                    "type": "object",
                    "properties": {"narration": {"type": "string"}},
                    "required": ["narration"],
                },
            }
        },
        "required": ["scenes"],
    }
    original = "\n".join(f"{i + 1}. {text}" for i, text in enumerate(narrations))
    prompt = f"""You are doing a final DIRECTOR'S EAR PASS on a short-form voiceover.
The facts and story are already approved. Your only job is to make the words sound like a real person talking into a microphone in one take.

TOPIC: {project.topic}
STYLE: {project.style}
ENTRIES: exactly {count}

DO NOT WRITE LIKE AN AI, ESSAY, TRAILER, OR MARKETING COPY.
- Keep every supported fact, name, number, uncertainty and causal relationship. Invent nothing and remove no important fact.
- Preserve the existing beat order. Each entry must still cover the same idea as its source entry.
- Use everyday spoken English. Contractions are good. Plain verbs beat abstract nouns.
- Let the rhythm breathe: mix short sentences with medium ones. A sentence should normally fit in one comfortable breath.
- It is okay for an occasional line to be blunt or slightly imperfect. Do not polish everything into symmetrical prose.
- Do not make every beat a mini cliffhanger. Do not explain the lesson or moral.
- The first sentence must hook with an actual fact, conflict, consequence, contradiction or specific detail. Usually make it a statement, not a question.
- Use natural connective tissue only when needed. Often a clean new sentence is better than "however", "meanwhile", "therefore" or "on the other hand".
- Avoid narrator filler such as "here's the thing", "the truth is", "at its core", "the reality is", "what makes this so...", "let that sink in".
- Avoid creator clichés: Did you know, Imagine this, Picture this, You won't believe, This is the story of, But here's the crazy part.
- Avoid repeated AI contrast formulas: "not X, but Y", "it wasn't just X, it was Y", or several sentences built the same way.
- Avoid stacks of rhetorical questions, dramatic em-dashes and one-word fragments.
- Do not add a CTA. The last line should simply land the final idea.
- Keep approximately the same total length. Do not pad.

READ-ALOUD TEST:
Before returning, silently read every line as if recording it. If a phrase feels like something people write but rarely say, simplify it.

APPROVED SCRIPT:
{original}

Return only the required JSON."""
    try:
        data = v080_script._json_call(service, model, prompt, schema, temperature=0.56)
    except Exception:
        return narrations
    candidate = [" ".join(str(row.get("narration", "")).split()).strip() for row in data.get("scenes", [])]
    if len(candidate) != count or not all(candidate):
        return narrations

    source_text = " ".join(narrations)
    candidate_text = " ".join(candidate)
    protected = _protected_tokens(source_text)
    missing = [token for token in protected if token.casefold() not in candidate_text.casefold()]
    if missing:
        return narrations

    before, _ = robotic_score(source_text)
    after, _ = robotic_score(candidate_text)
    # Accept equal-scoring rewrites too: the model can improve word choice/prosody in ways the
    # lightweight checker cannot see. Reject only a clearly more templated result.
    if after > before + 1:
        return narrations
    return candidate


def natural_script_generate(self, project, scene_count: int):
    original = getattr(natural_script_generate, "_original", None)
    if original is None:
        raise RuntimeError("Natural script layer was not initialized")
    script, scenes = original(self, project, scene_count)
    mode = getattr(project, "script_mode", "AI Script") or "AI Script"
    if mode == "Custom Script" or not scenes:
        return script, scenes

    model_mode = getattr(project, "script_model_mode", "Auto Quality") or "Auto Quality"
    model = getattr(project, "script_model_used", "") or v080_script.resolve_writer_model(self.settings, model_mode)[0]
    narrations = [scene.narration for scene in scenes]
    before_text = " ".join(narrations)
    before_score, before_flags = robotic_score(before_text)
    v080_script._progress(self, 12, "Director's Ear Pass • reading narration out loud for human cadence")
    candidate = _ear_pass(self, project, model, narrations)
    after_text = " ".join(candidate)
    after_score, after_flags = robotic_score(after_text)

    if candidate == narrations:
        project.script_quality_summary = (
            (getattr(project, "script_quality_summary", "") or "Story Director")
            + f" • Ear Pass kept original ({before_score} cadence flags)"
        )
        return script, scenes

    # Re-plan images against the FINAL spoken wording so the extra naturalization pass cannot
    # leave visual prompts tied to old phrasing.
    try:
        title, anchor, continuity, prompts = v080_script._visual_plan(self, project, model, candidate)
        scenes = v080_script._build_scenes(project, candidate, prompts, anchor, continuity)
        if title:
            project.title = title
    except Exception:
        # A visual-plan retry should never cost the user an otherwise usable script.
        for scene, text in zip(scenes, candidate):
            scene.narration = text

    project.script = after_text
    flag_text = ", ".join(after_flags[:2]) if after_flags else "natural cadence"
    project.script_quality_summary = (
        f"Story Director v2 + Director's Ear Pass • robotic score {before_score}→{after_score} • {flag_text}"
    )
    v080_script._progress(self, 13, project.script_quality_summary)
    return project.script, scenes


FAST_CLONE_RUNNER = r'''from pathlib import Path
import argparse
import re
import numpy as np
import soundfile as sf
import torch
from chatterbox.tts_turbo import ChatterboxTurboTTS

p=argparse.ArgumentParser()
p.add_argument('--text-file')
p.add_argument('--ref')
p.add_argument('--out')
p.add_argument('--device', default='auto')
p.add_argument('--pause-ms', type=int, default=145)
a=p.parse_args()
text=Path(a.text_file).read_text(encoding='utf-8').strip()
if not text:
    raise SystemExit('empty narration')

def choose_device(requested):
    if requested == 'auto':
        return 'cuda' if torch.cuda.is_available() else 'cpu'
    return requested

device=choose_device(a.device)
model=ChatterboxTurboTTS.from_pretrained(device=device)

# Turbo is quickest and most stable on narration-sized chunks. Keep sentence boundaries so
# the clone sounds continuous rather than resetting every scene.
sentences=[s.strip() for s in re.split(r'(?<=[.!?…])\s+', text) if s.strip()]
chunks=[]
current=''
for sentence in sentences:
    proposed=(current + ' ' + sentence).strip()
    if current and len(proposed) > 420:
        chunks.append(current)
        current=sentence
    else:
        current=proposed
if current:
    chunks.append(current)
if not chunks:
    chunks=[text]

pieces=[]
for chunk in chunks:
    wav=model.generate(chunk, audio_prompt_path=a.ref)
    arr=wav.detach().float().cpu().numpy()
    while getattr(arr, 'ndim', 1) > 1 and arr.shape[0] == 1:
        arr=arr[0]
    pieces.append(arr.astype('float32', copy=False))

if len(pieces) > 1:
    silence=np.zeros(max(1, int(model.sr * max(0, a.pause_ms) / 1000.0)), dtype='float32')
    merged=[]
    for i, piece in enumerate(pieces):
        if i:
            merged.append(silence)
        merged.append(piece)
    audio=np.concatenate(merged)
else:
    audio=pieces[0]
sf.write(a.out, audio, model.sr, subtype='PCM_16')
print('ZEROREELS_FAST_CLONE_DEVICE=' + device)
print('ZEROREELS_FAST_CLONE_CHUNKS=' + str(len(chunks)))
'''


class FastCloneVoiceService:
    def __init__(self, settings, delivery: str):
        self.settings = settings
        self.delivery = delivery
        self.engine = FAST_CLONE_ENGINE

    def generate(self, project, out_dir: Path, progress=None) -> Path:
        python_exe = Path(getattr(self.settings, "chatterbox_python", "") or "").expanduser()
        ref = Path(getattr(self.settings, "natural_voice_ref", "") or "").expanduser()
        if not python_exe.exists():
            return v075_voice_fix._fallback_to_kokoro(
                self, project, out_dir, progress, "Chatterbox environment is not installed"
            )
        if not ref.exists():
            return v075_voice_fix._fallback_to_kokoro(
                self, project, out_dir, progress, "Fast Voice Clone reference WAV is missing"
            )

        v070_voice._progress(progress, 20, f"Fast Voice Clone • Chatterbox Turbo • {self.delivery}")
        out_dir.mkdir(parents=True, exist_ok=True)
        text_path = out_dir / "voice_directed.txt"
        text_path.write_text(v070_voice.directed_script(project, self.delivery), encoding="utf-8")
        runner = out_dir / "_fast_clone_runner.py"
        runner.write_text(FAST_CLONE_RUNNER, encoding="utf-8")
        target = out_dir / "narration.wav"
        pause_ms = round(float(v070_voice.DELIVERY_PROFILES.get(self.delivery, v070_voice.DELIVERY_PROFILES["Natural Storyteller"])["pause"]) * 720)

        def run(device: str):
            return run_hidden(
                [
                    str(python_exe), str(runner), "--text-file", str(text_path), "--ref", str(ref),
                    "--out", str(target), "--device", device, "--pause-ms", str(max(85, min(240, pause_ms))),
                ],
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
                timeout=1800,
            )

        try:
            proc = run("auto")
        except Exception as exc:
            proc = None
            first_error = str(exc)
        else:
            first_error = (proc.stderr or proc.stdout or "") if proc.returncode else ""

        # CUDA is preferred because this stage runs before FLUX. If the local torch/chatterbox
        # stack cannot use the GPU or hits VRAM trouble, retry once on CPU instead of aborting.
        if proc is None or proc.returncode != 0 or not target.exists() or target.stat().st_size < 1000:
            v070_voice._progress(progress, 23, "Fast Voice Clone GPU/auto pass unavailable • retrying on CPU")
            try:
                target.unlink(missing_ok=True)
                proc = run("cpu")
            except Exception as exc:
                try:
                    runner.unlink(missing_ok=True)
                except OSError:
                    pass
                return v075_voice_fix._fallback_to_kokoro(
                    self, project, out_dir, progress, first_error + "\n" + str(exc)
                )

        try:
            runner.unlink(missing_ok=True)
        except OSError:
            pass

        if proc.returncode != 0 or not target.exists() or target.stat().st_size < 1000:
            detail = (proc.stderr or proc.stdout or first_error or "unknown Chatterbox Turbo error")[-4000:]
            return v075_voice_fix._fallback_to_kokoro(self, project, out_dir, progress, detail)

        stdout = proc.stdout or ""
        device = "CUDA" if "ZEROREELS_FAST_CLONE_DEVICE=cuda" in stdout else "CPU"
        duration = v070_voice._wav_duration(target)
        v070_voice.apply_scene_timing(project, duration, self.delivery)
        project.actual_seconds = round(duration, 2)
        project.voice_engine_used = f"{FAST_CLONE_ENGINE} ({device})"
        project.voice_delivery = self.delivery
        v070_voice._progress(progress, 29, f"Fast Voice Clone ready • {duration:.1f}s • {device}")
        return target


def voice_service_for_v082(settings, engine: str, delivery: str, mock_mode: bool = False):
    original = getattr(voice_service_for_v082, "_original", None)
    if engine == FAST_CLONE_ENGINE and not mock_mode:
        return FastCloneVoiceService(settings, delivery)
    if original is None:
        return v070_voice.KokoroDirectedVoiceService(settings, delivery)
    return original(settings, engine, delivery, mock_mode)


def install() -> None:
    # Script layer: capture Story Director v2 only after its own install has run.
    natural_script_generate._original = services.ScriptService.generate
    services.ScriptService.generate = natural_script_generate

    # Voice layer: pipeline modules imported this symbol directly, so patch all live bindings.
    voice_service_for_v082._original = v070_voice.voice_service_for
    v070_voice.voice_service_for = voice_service_for_v082
    v070_pipeline.voice_service_for = voice_service_for_v082
    v071_pipeline.voice_service_for = voice_service_for_v082

    original_sidebar = ui.MainWindow._sidebar
    original_create_page = ui.MainWindow._create_page
    original_setup_page = ui.MainWindow._setup_page

    def sidebar(self):
        frame = original_sidebar(self)
        for label in frame.findChildren(QLabel):
            if label.text().startswith("v0."):
                label.setText("v0.8.2 NATURAL")
                label.setMaximumWidth(138)
                break
        return frame

    def create_page(self):
        page = original_create_page(self)
        box = getattr(self, "voice_engine_box", None)
        if box is not None:
            items = [box.itemText(i) for i in range(box.count())]
            if FAST_CLONE_ENGINE not in items:
                insert_at = 2 if box.count() >= 2 else box.count()
                box.insertItem(insert_at, FAST_CLONE_ENGINE)
            box.setToolTip(
                "Kokoro Directed is built in. Chatterbox Turbo Fast Clone copies the voice character from your reference WAV and prefers CUDA for speed. Chatterbox Nano is the slower CPU-friendly clone mode; F5-TTS Studio is the heavier clone option."
            )
        return page

    def setup_page(self):
        page = original_setup_page(self)
        for label in page.findChildren(QLabel):
            if label.text() != "Voice":
                continue
            card = label.parentWidget()
            if not card or not card.layout():
                continue
            note = QLabel(
                "Fast Voice Clone uses the same Chatterbox install and reference WAV, but runs Chatterbox Turbo on CUDA when available. Voice generation happens before FLUX, so the GPU is free for this stage and the process releases VRAM before images start."
            )
            note.setObjectName("Hint")
            note.setWordWrap(True)
            button = ui.SoftButton("Install / Repair Fast Voice Clone (Chatterbox Turbo)")
            button.clicked.connect(
                lambda checked=False: self._run_setup(
                    "Fast Voice Clone ready",
                    lambda progress, log: v075_voice_fix.install_optional_voice_engine_compat(
                        self.settings, "Chatterbox Nano", progress
                    ),
                )
            )
            card.layout().addWidget(note)
            card.layout().addWidget(button)
            break
        return page

    ui.MainWindow._sidebar = sidebar
    ui.MainWindow._create_page = create_page
    ui.MainWindow._setup_page = setup_page
