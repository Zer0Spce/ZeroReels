from __future__ import annotations

from difflib import SequenceMatcher
import hashlib
import json
import queue
import re
import time

from PySide6.QtCore import QThread, QTimer, Signal
from PySide6.QtWidgets import QLabel

from . import services, ui
from .models import Scene

STYLE_PROFILES = {
    "TikTok Story": "Conversational short-form storyteller. Strong curiosity hook, clean escalation, simple spoken language, short-to-medium sentences, occasional punchy fragments, and a memorable final line. Never sound like a textbook or ad.",
    "Viral Explainer": "Fast, clear explainer with strong retention. Explain one idea at a time in plain language, use concrete consequences, and keep momentum high without fake hype or clickbait cliches.",
    "Dark Curiosity": "Understated, tense curiosity narration. Calm but intriguing, visual and specific, with restrained suspense instead of melodrama.",
    "Mini Documentary": "Human documentary narration: precise, cinematic, natural, factual when factual, with a strong opening and clean ending.",
    "Cinematic Documentary": "Cinematic documentary narration with natural spoken rhythm, specific imagery, restrained emotion, and no generic documentary filler.",
    "Dark Mystery": "Measured mystery narration with concise sentences, controlled tension, and concrete sensory detail. Avoid purple prose.",
    "Clean Educational": "Friendly educational narration that sounds spoken, not read from a textbook. Use simple explanations and concrete examples.",
    "Fast Social": "Fast social narration with short sentences, direct phrasing, and frequent forward motion. Keep it natural, never shouty.",
    "Retro Film": "Warm story-driven narration with a subtle archival feel while still sounding modern and conversational.",
    "Anime Inspired": "Emotionally clear story narration with vivid but concise beats. Keep dialogue-like rhythm without melodramatic exposition.",
}

SHOT_ROLES = (
    "hook image with one immediately readable visual idea",
    "wide establishing shot that makes the situation easy to understand",
    "medium action shot showing the next consequence or story beat",
    "close detail shot focused on the most meaningful object, reaction, or physical effect",
    "new angle showing escalation with clear foreground and background depth",
    "largest-impact visual beat with strong scale and believable physical detail",
    "aftermath or context shot that changes the visual rhythm",
    "clean final image with a memorable, slightly reflective composition",
)


def _progress(service, value: int, text: str) -> None:
    callback = getattr(service, "_zr_progress", None)
    if callback:
        callback(value, text)


def _normalize(text: str) -> str:
    return " ".join(re.findall(r"[a-z0-9']+", (text or "").lower()))


def _similarity(a: str, b: str) -> float:
    aa, bb = _normalize(a), _normalize(b)
    return SequenceMatcher(None, aa, bb).ratio() if aa and bb else 0.0


def _too_repetitive(scenes: list[Scene]) -> bool:
    texts = [scene.narration for scene in scenes]
    normalized = [_normalize(text) for text in texts]
    if len(set(normalized)) != len(normalized):
        return True
    for i in range(len(texts)):
        for j in range(i + 1, len(texts)):
            threshold = 0.73 if j == i + 1 else 0.82
            if _similarity(texts[i], texts[j]) >= threshold:
                return True
    return False


def _continuity_rule(mode: str) -> str:
    if mode == "Same Cast & World":
        return "Keep recurring people extremely consistent: same age range, face description, hair, wardrobe, build, props and world design. But EVERY scene must be a newly generated shot with a new camera position, action, composition or distance."
    if mode == "Independent Shots":
        return "Do not force recurring characters. Each scene may use the strongest standalone visual for that beat, while keeping the chosen art/film style coherent."
    return "Keep recurring people, locations, era, palette and props coherent when they naturally recur, but every scene must still advance visually with a fresh shot."


def _style_profile(style: str) -> str:
    return STYLE_PROFILES.get(style, STYLE_PROFILES["TikTok Story"])


def _build_scene_prompt(project, visual_anchor: str, continuity_bible: str, raw_prompt: str, index: int, base_seed: int) -> str:
    mode = getattr(project, "continuity_mode", "Consistent Story")
    if mode == "Independent Shots":
        continuity = ""
        seed = (base_seed + index * 15_485_863) % 2_147_483_647
    elif mode == "Same Cast & World":
        continuity = f"Continuity lock: {continuity_bible}. "
        seed = (base_seed + index * 104_729) % 2_147_483_647
    else:
        continuity = f"Continuity guide: {continuity_bible}. "
        seed = (base_seed + index * 65_537) % 2_147_483_647
    if seed <= 0:
        seed = index + 1
    role = SHOT_ROLES[index % len(SHOT_ROLES)]
    return (
        f"{visual_anchor}. {continuity}Story beat {index + 1}: {raw_prompt}. "
        f"Shot purpose: {role}. Fresh composition, visibly different from the previous shot, one clear focal subject, "
        "natural pose and anatomy, believable hands, physically coherent scale and perspective, cinematic depth, realistic material detail, "
        "no collage, no split screen, no duplicated person, no readable text, no letters, no signage, no logo, no watermark, no UI, "
        f"no legible document, no subtitles [ZR-SEED={seed}]"
    )


def _tiktok_script_generate(self, project, scene_count: int):
    target_words = max(55, round(project.target_seconds * 2.45))
    words_per_scene = max(9, round(target_words / max(1, scene_count)))
    continuity_mode = getattr(project, "continuity_mode", "Consistent Story")
    profile = _style_profile(project.style)
    continuity = _continuity_rule(continuity_mode)
    schema = {
        "type": "object",
        "properties": {
            "title": {"type": "string"},
            "visual_anchor": {"type": "string"},
            "continuity_bible": {"type": "string"},
            "scenes": {
                "type": "array", "minItems": scene_count, "maxItems": scene_count,
                "items": {"type": "object", "properties": {"beat": {"type": "string"}, "narration": {"type": "string"}, "image_prompt": {"type": "string"}}, "required": ["beat", "narration", "image_prompt"]},
            },
        },
        "required": ["title", "visual_anchor", "continuity_bible", "scenes"],
    }
    _progress(self, 7, "Planning TikTok story structure")
    prompt = f"""You are writing and visually directing a polished TikTok/Reels narration video.

TOPIC: {project.topic}
STYLE: {project.style}
VOICE PROFILE: {profile}
TARGET LENGTH: about {project.target_seconds} seconds, about {target_words} spoken words total
SCENES: exactly {scene_count}, roughly {words_per_scene} words per scene
CONTINUITY MODE: {continuity_mode}
CONTINUITY RULE: {continuity}

STORY SHAPE
- Scene 1: hook immediately. Give the viewer a concrete reason to keep listening within the first sentence.
- Scene 2: make the premise crystal clear.
- Middle scenes: escalate one new consequence, discovery, action, or piece of context at a time. Every scene MUST add new information.
- Penultimate scene: strongest consequence, reveal, or emotional/visual peak.
- Final scene: land the idea with one memorable natural line. No generic CTA.

NARRATION RULES
- Write exactly like a skilled human short-form narrator speaks aloud.
- Prefer contractions, plain words, active verbs, and short-to-medium sentences.
- Use occasional short fragments for rhythm, but don't overdo them.
- Avoid essay language: therefore, furthermore, consequently, in conclusion, one must consider, it is important to note.
- Avoid AI/TikTok cliches: 'But here's the crazy part', 'You won't believe', 'This changes everything', 'Let that sink in', 'Imagine this' unless genuinely necessary.
- Do not repeat the same opening structure or paraphrase the previous scene.
- Never summarize the same fact twice just to fill time.
- Do not mention scenes, prompts, visuals, viewers, or the production process.
- For factual topics, never invent facts, quotes, numbers, dates, studies or events. If the topic is hypothetical, clearly explain plausible consequences without presenting speculation as a sourced fact.
- Make the whole narration feel like one person telling one story, not disconnected captions.

VISUAL RULES
- visual_anchor: concise production design only: medium/style, palette, lighting, era, lens/texture language.
- continuity_bible: concise stable traits for recurring people/places/props. Do NOT describe camera framing here.
- Each image_prompt must show the specific NEW beat of that scene, not the whole story.
- Each scene must have a visibly different action, framing, distance, angle or environment detail from the previous scene.
- Favor believable documentary/storytelling frames over poster-like hero shots.
- Do not request readable text, screens, labels, maps with legible writing, newspapers, logos, UI or subtitles.
- If a sign/map/document is relevant, make it abstract, folded, cropped, blurred or unreadable.

Return ONLY JSON matching the schema."""
    endpoint = self.settings.ollama_url.rstrip("/") + "/api/generate"
    result = services._post_json(endpoint, {"model": self.settings.ollama_model, "prompt": prompt, "stream": False, "format": schema, "think": False, "options": {"temperature": 0.52, "top_p": 0.92, "repeat_penalty": 1.08}}, timeout=600)
    _progress(self, 10, "Story draft ready • polishing spoken narration")
    try:
        data = json.loads(result["response"])
    except Exception as exc:
        raise RuntimeError("Ollama returned invalid structured output") from exc
    raw = data.get("scenes", [])
    if len(raw) != scene_count:
        raise RuntimeError(f"Ollama returned {len(raw)} scenes; expected {scene_count}")
    visual_anchor = " ".join(str(data.get("visual_anchor", "")).split()).strip() or f"{project.style}, cohesive cinematic lighting, natural texture, consistent production design"
    continuity_bible = " ".join(str(data.get("continuity_bible", "")).split()).strip() or "keep recurring subjects, wardrobe, locations, props, era and physical traits stable when they recur"
    seed_material = f"{project.topic}|{project.style}|{visual_anchor}|{continuity_bible}".encode("utf-8")
    base_seed = int(hashlib.sha256(seed_material).hexdigest()[:8], 16) % 2_147_483_647
    provisional = max(2.0, project.target_seconds / max(1, scene_count))
    scenes: list[Scene] = []
    for i, item in enumerate(raw):
        narration = " ".join(str(item.get("narration", "")).split()).strip()
        visual = " ".join(str(item.get("image_prompt", "")).split()).strip()
        if not narration or not visual:
            raise RuntimeError("Ollama returned an incomplete scene")
        scenes.append(Scene(index=i + 1, narration=narration, image_prompt=_build_scene_prompt(project, visual_anchor, continuity_bible, visual, i, base_seed), duration=provisional, reuse_previous_image=False))

    polish_schema = {"type": "object", "properties": {"scenes": {"type": "array", "minItems": scene_count, "maxItems": scene_count, "items": {"type": "object", "properties": {"narration": {"type": "string"}}, "required": ["narration"]}}}, "required": ["scenes"]}
    draft = "\n".join(f"{i + 1}. {scene.narration}" for i, scene in enumerate(scenes))
    polish_prompt = f"""Polish this short-form narration as a human TikTok/Reels script editor.
TOPIC: {project.topic}
TARGET: about {target_words} words total
STYLE: {profile}

Rules:
- Keep exactly {scene_count} scene entries.
- Preserve meaning and factual caution. Add NO new facts, dates, numbers, quotes, names, studies or events.
- Make the opening sharper and more immediate.
- Make each scene advance naturally from the previous one.
- Remove repeated ideas, repeated sentence shapes, filler and formal essay wording.
- Use contractions and natural punctuation where appropriate.
- Vary sentence length. One short punchy sentence is fine; don't make every line punchy.
- Avoid canned phrases and fake hype.
- The final line should feel like a satisfying landing, not a summary paragraph or CTA.
- Return ONLY the required JSON.

DRAFT:\n{draft}"""
    try:
        polished = services._post_json(endpoint, {"model": self.settings.ollama_model, "prompt": polish_prompt, "stream": False, "format": polish_schema, "think": False, "options": {"temperature": 0.36, "top_p": 0.9, "repeat_penalty": 1.1}}, timeout=600)
        pdata = json.loads(polished["response"])
        pscenes = pdata.get("scenes", [])
        if len(pscenes) == scene_count:
            candidate = [" ".join(str(item.get("narration", "")).split()).strip() for item in pscenes]
            if all(candidate):
                for scene, text in zip(scenes, candidate):
                    scene.narration = text
    except Exception:
        pass

    _progress(self, 12, "Checking narration flow and repetition")
    if _too_repetitive(scenes):
        repair_prompt = f"""The narration below repeats or paraphrases itself too much.
Rewrite ONLY the narration, keeping exactly {scene_count} entries and the same topic/facts.
Every entry must introduce a distinct next beat. Never repeat a clause longer than 6 words from another entry unless it is an unavoidable proper name.
Keep the voice conversational, natural and suitable for a TikTok/Reels narrator. Do not add new facts.

NARRATION:\n""" + "\n".join(f"{i + 1}. {s.narration}" for i, s in enumerate(scenes))
        repaired = services._post_json(endpoint, {"model": self.settings.ollama_model, "prompt": repair_prompt, "stream": False, "format": polish_schema, "think": False, "options": {"temperature": 0.58, "top_p": 0.92, "repeat_penalty": 1.14}}, timeout=600)
        rdata = json.loads(repaired["response"])
        rscenes = rdata.get("scenes", [])
        if len(rscenes) == scene_count:
            for scene, item in zip(scenes, rscenes):
                value = " ".join(str(item.get("narration", "")).split()).strip()
                if value:
                    scene.narration = value
        if _too_repetitive(scenes):
            raise RuntimeError("The local script model still produced repetitive narration after a repair pass. ZeroReels stopped before generating images. Try Generate again.")
    project.title = str(data.get("title") or project.topic).strip()[:100]
    _progress(self, 13, "Narration locked • starting visual generation")
    return " ".join(scene.narration for scene in scenes).strip(), scenes


class ReliablePipelineThread(QThread):
    progress_changed = Signal(int, str)
    completed = Signal(object)
    failed = Signal(str)

    def __init__(self, pipeline, project, options):
        super().__init__()
        self.pipeline = pipeline
        self.project = project
        self.options = options
        self.events: queue.Queue[tuple[int, str]] = queue.Queue()

    def _report(self, value: int, text: str) -> None:
        self.events.put((int(value), str(text)))

    def run(self):
        try:
            result = self.pipeline.run(self.project, self.options, self._report)
            self.completed.emit(result)
        except Exception as exc:
            self.failed.emit(str(exc))


def _elapsed(seconds: float) -> str:
    seconds = max(0, int(seconds))
    return f"{seconds // 60:02d}:{seconds % 60:02d}"


def _drain_events(window) -> int:
    worker = getattr(window, "worker", None)
    if not worker or not hasattr(worker, "events"):
        return 0
    count = 0
    while True:
        try:
            value, text = worker.events.get_nowait()
        except queue.Empty:
            break
        count += 1
        window._generation_progress_value = value
        window._generation_stage = text
        window._generation_last_event_at = time.monotonic()
        window._on_progress(value, text)
    return count


def install() -> None:
    services.ScriptService.generate = _tiktok_script_generate
    ui.PipelineThread = ReliablePipelineThread
    original_sidebar = ui.MainWindow._sidebar
    original_create_page = ui.MainWindow._create_page
    original_generate = ui.MainWindow._generate
    original_complete = ui.MainWindow._on_complete
    original_failed = ui.MainWindow._on_failed

    def sidebar(self):
        frame = original_sidebar(self)
        for label in frame.findChildren(QLabel):
            if label.text() == "v0.5.2":
                label.setText("v0.5.3")
                label.setMaximumWidth(82)
        return frame

    def create_page(self):
        page = original_create_page(self)
        existing = [self.style_box.itemText(i) for i in range(self.style_box.count())]
        presets = ["TikTok Story", "Viral Explainer", "Dark Curiosity", "Mini Documentary"]
        for name in reversed(presets):
            if name not in existing:
                self.style_box.insertItem(0, name)
        self.style_box.setCurrentText("TikTok Story")
        self.style_box.setToolTip("TikTok Story is the recommended default: conversational hook, escalating beats, natural spoken rhythm and a clean landing.")
        return page

    def poll(self):
        drained = _drain_events(self)
        worker = getattr(self, "worker", None)
        if not worker or not worker.isRunning():
            if drained == 0 and getattr(self, "_generation_event_timer", None):
                self._generation_event_timer.stop()
            return
        now = time.monotonic()
        started = getattr(self, "_generation_started_at", now)
        last_event = getattr(self, "_generation_last_event_at", started)
        stage = getattr(self, "_generation_stage", "Initializing local pipeline")
        value = int(getattr(self, "_generation_progress_value", 1))
        if hasattr(self, "status_detail"):
            self.status_detail.setText(f"{value}% • {stage} • elapsed {_elapsed(now - started)}")
        quiet = now - last_event
        bucket = int(quiet // 20)
        last_bucket = getattr(self, "_generation_quiet_bucket", -1)
        if quiet >= 20 and bucket != last_bucket:
            self._generation_quiet_bucket = bucket
            if hasattr(self, "_append_create_log"):
                self._append_create_log(f"… {stage} is still running • elapsed {_elapsed(now - started)}")

    def generate(self):
        self._generation_started_at = time.monotonic()
        self._generation_last_event_at = self._generation_started_at
        self._generation_stage = "Initializing local pipeline"
        self._generation_progress_value = 1
        self._generation_quiet_bucket = -1
        result = original_generate(self)
        worker = getattr(self, "worker", None)
        if worker and worker.isRunning():
            if not hasattr(self, "_generation_event_timer"):
                self._generation_event_timer = QTimer(self)
                self._generation_event_timer.setInterval(180)
                self._generation_event_timer.timeout.connect(lambda: poll(self))
            self._generation_event_timer.start()
            if hasattr(self, "_append_create_log"):
                self._append_create_log("Live stage tracking connected to the generation worker.")
            poll(self)
        return result

    def complete(self, project):
        _drain_events(self)
        timer = getattr(self, "_generation_event_timer", None)
        if timer:
            timer.stop()
        return original_complete(self, project)

    def failed(self, message: str):
        _drain_events(self)
        timer = getattr(self, "_generation_event_timer", None)
        if timer:
            timer.stop()
        return original_failed(self, message)

    ui.MainWindow._sidebar = sidebar
    ui.MainWindow._create_page = create_page
    ui.MainWindow._generate = generate
    ui.MainWindow._on_complete = complete
    ui.MainWindow._on_failed = failed
