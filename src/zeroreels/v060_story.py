from __future__ import annotations

from difflib import SequenceMatcher
from pathlib import Path
import json
import math
import re

from PySide6.QtGui import QImage

from . import services
from .models import Project, Scene


SHOT_ROLES = (
    "Hook",
    "Establishing",
    "Action",
    "Detail",
    "Escalation",
    "Peak",
    "Aftermath",
    "Landing",
)

ROLE_DIRECTIONS = {
    "Hook": "Open on an instantly readable visual event. Avoid a static centered portrait; show the premise happening.",
    "Establishing": "Use a wide environmental shot with clear geography and scale. Keep any person smaller in frame.",
    "Action": "Show candid mid-action storytelling, not a posed hero portrait. Give the subject a clear physical task or consequence.",
    "Detail": "Prefer meaningful B-roll: a close object, physical effect, texture, mechanism, hands-at-work, or environmental detail. Avoid another face-first portrait.",
    "Escalation": "Show the consequence growing with layered foreground/background depth and a noticeably different camera angle.",
    "Peak": "Use the strongest scale/reveal image of the sequence. Prioritize the event or consequence over a person posing for camera.",
    "Aftermath": "Change the rhythm with a calmer context or aftermath shot. Favor environment, traces, objects, or distant human scale.",
    "Landing": "Finish on one clean memorable image with simple composition and emotional or conceptual closure, not a poster pose.",
}

STOPWORDS = {
    "the", "a", "an", "and", "or", "but", "if", "then", "than", "this", "that", "these", "those",
    "is", "are", "was", "were", "be", "been", "being", "to", "of", "in", "on", "at", "for", "from",
    "with", "as", "by", "it", "its", "they", "their", "you", "your", "we", "our", "he", "she", "his",
    "her", "not", "just", "so", "very", "can", "could", "would", "should", "will", "into", "about",
}


def _progress(service, value: int, text: str) -> None:
    callback = getattr(service, "_zr_progress", None)
    if callback:
        callback(value, text)


def _word_count(text: str) -> int:
    return len(re.findall(r"\b[\w’'-]+\b", text or ""))


def _scene_role(index: int, count: int) -> str:
    if count <= 1:
        return "Hook"
    if index == 0:
        return "Hook"
    if index == count - 1:
        return "Landing"
    if index == count - 2:
        return "Aftermath"
    if count >= 6 and index == count - 3:
        return "Peak"
    middle = ("Establishing", "Action", "Detail", "Escalation", "Action", "Detail")
    return middle[(index - 1) % len(middle)]


def _seed_from_prompt(prompt: str) -> int:
    match = re.search(r"\[ZR-SEED=(\d+)\]", prompt or "")
    return int(match.group(1)) if match else 0


def _apply_professional_visual_direction(project: Project, scenes: list[Scene]) -> None:
    count = len(scenes)
    hero_lock = project.continuity_mode == "Hero Character Lock"
    for i, scene in enumerate(scenes):
        role = _scene_role(i, count)
        scene.shot_role = role
        scene.reuse_previous_image = False
        scene.seed = _seed_from_prompt(scene.image_prompt)
        role_direction = ROLE_DIRECTIONS[role]
        broll = ""
        if role in {"Establishing", "Detail", "Aftermath"}:
            broll = " Treat this as B-roll first; do not default to a centered waist-up person."
        hero = ""
        if hero_lock:
            hero = (
                " Hero identity lock: whenever the recurring lead appears, preserve the exact same described age range, "
                "facial structure, hair, build, skin tone, wardrobe silhouette and signature props. Do not redesign the lead."
            )
        scene.image_prompt = (
            scene.image_prompt.rstrip()
            + f" Professional shot role: {role}. {role_direction}{broll}{hero} "
              "Single full-frame image only; no montage, no contact sheet, no comic panels, no framed inset image, no split screen."
        )


def _duration_fit(self, project: Project, scenes: list[Scene]) -> None:
    target_words = max(55, round(project.target_seconds * 2.45))
    current = sum(_word_count(scene.narration) for scene in scenes)
    low = round(target_words * 0.93)
    high = round(target_words * 1.07)
    if low <= current <= high:
        return

    _progress(self, 12, f"Duration fit • {current} words → target {low}-{high}")
    schema = {
        "type": "object",
        "properties": {
            "scenes": {
                "type": "array",
                "minItems": len(scenes),
                "maxItems": len(scenes),
                "items": {
                    "type": "object",
                    "properties": {"narration": {"type": "string"}},
                    "required": ["narration"],
                },
            }
        },
        "required": ["scenes"],
    }
    draft = "\n".join(f"{i + 1}. {scene.narration}" for i, scene in enumerate(scenes))
    prompt = f"""Fit this spoken short-form narration to a real {project.target_seconds}-second delivery.

TARGET TOTAL WORDS: between {low} and {high} words.
TOPIC: {project.topic}
STYLE: {project.style}

Rules:
- Keep exactly {len(scenes)} scene entries.
- Preserve the existing facts, meaning, uncertainty, names and numbers. Add NO new factual claims.
- If the draft is short, deepen existing explanation with concrete consequences or sensory clarity already implied by the draft; do not pad with repetition.
- If it is long, tighten wording without removing the logical progression.
- Scene 1 must hook immediately in natural spoken language.
- Every middle scene must advance a distinct beat; never paraphrase the previous one.
- The final scene must end on one natural memorable landing line, not a summary paragraph or CTA.
- Use contractions and spoken English. Avoid essay language and canned AI/TikTok phrases.
- Return ONLY the required JSON.

DRAFT:\n{draft}"""
    try:
        endpoint = self.settings.ollama_url.rstrip("/") + "/api/generate"
        result = services._post_json(
            endpoint,
            {
                "model": self.settings.ollama_model,
                "prompt": prompt,
                "stream": False,
                "format": schema,
                "think": False,
                "options": {"temperature": 0.42, "top_p": 0.90, "repeat_penalty": 1.10},
            },
            timeout=600,
        )
        data = json.loads(result["response"])
        rewritten = data.get("scenes", [])
        if len(rewritten) == len(scenes):
            values = [" ".join(str(item.get("narration", "")).split()).strip() for item in rewritten]
            if all(values):
                for scene, value in zip(scenes, values):
                    scene.narration = value
    except Exception:
        # Duration fitting improves quality but must not turn a usable draft into a hard failure.
        pass


def professional_script_generate(original_generate, self, project: Project, scene_count: int):
    requested_mode = project.continuity_mode
    # Hero Character Lock uses the strongest existing continuity prompt, then adds
    # a stricter identity lock after the base story/visual planning pass.
    if requested_mode == "Hero Character Lock":
        project.continuity_mode = "Same Cast & World"
    try:
        script, scenes = original_generate(self, project, scene_count)
    finally:
        project.continuity_mode = requested_mode

    _duration_fit(self, project, scenes)
    _apply_professional_visual_direction(project, scenes)
    script = " ".join(scene.narration for scene in scenes).strip()
    _progress(self, 13, "Professional story pass locked")
    return script, scenes


def _small_grayscale(path: str | Path, size: int = 64) -> tuple[list[int], int, int] | None:
    image = QImage(str(path))
    if image.isNull() or image.width() < 16 or image.height() < 16:
        return None
    image = image.convertToFormat(QImage.Format_Grayscale8).scaled(size, size)
    values: list[int] = []
    for y in range(image.height()):
        for x in range(image.width()):
            values.append(image.pixelColor(x, y).red())
    return values, image.width(), image.height()


def _average_hash(path: str | Path) -> int | None:
    sample = _small_grayscale(path, 8)
    if not sample:
        return None
    values, _, _ = sample
    mean = sum(values) / len(values)
    bits = 0
    for value in values:
        bits = (bits << 1) | int(value >= mean)
    return bits


def _hash_distance(a: int | None, b: int | None) -> int:
    if a is None or b is None:
        return 64
    return (a ^ b).bit_count()


def scene_quality_report(path: str | Path, previous_path: str | Path | None = None) -> tuple[int, list[str], bool]:
    sample = _small_grayscale(path, 64)
    if not sample:
        return 0, ["invalid or unreadable image"], False
    values, width, height = sample
    count = len(values)
    mean = sum(values) / count
    variance = sum((value - mean) ** 2 for value in values) / count
    std = math.sqrt(variance)
    dynamic = max(values) - min(values)

    edge_values: list[int] = []
    for y in range(height):
        row = y * width
        for x in range(width - 1):
            edge_values.append(abs(values[row + x + 1] - values[row + x]))
    for y in range(height - 1):
        row = y * width
        nxt = (y + 1) * width
        for x in range(width):
            edge_values.append(abs(values[nxt + x] - values[row + x]))
    edge_mean = sum(edge_values) / max(1, len(edge_values))

    mid_x = width // 2
    mid_y = height // 2
    vseam = sum(abs(values[y * width + mid_x] - values[y * width + mid_x - 1]) for y in range(height)) / height
    hseam = sum(abs(values[mid_y * width + x] - values[(mid_y - 1) * width + x]) for x in range(width)) / width
    seam = max(vseam, hseam)
    seam_ratio = seam / max(1.0, edge_mean)

    score = 100
    notes: list[str] = []
    severe = False
    if mean < 13:
        score -= 45; notes.append("image is extremely dark")
    elif mean > 246:
        score -= 45; notes.append("image is severely overexposed")
    if std < 13:
        score -= 28; notes.append("image has very low visual separation")
    if dynamic < 48:
        score -= 22; notes.append("image has unusually low dynamic range")
    if seam > 42 and seam_ratio > 5.2:
        score -= 34; notes.append("possible collage/split-panel seam")
    if edge_mean < 3.0:
        score -= 24; notes.append("image is unusually flat or blank")

    if previous_path:
        distance = _hash_distance(_average_hash(path), _average_hash(previous_path))
        if distance <= 3:
            score -= 48
            notes.append("near-duplicate of previous scene")
            severe = True

    score = max(0, min(100, int(round(score))))
    accepted = score >= 58 and not severe
    if not notes:
        notes.append("visual checks passed")
    return score, notes, accepted


def quality_retry_prompt(scene: Scene, attempt: int) -> str:
    prompt = re.sub(r"\s*Quality retry \d+:.*?(?=\[ZR-SEED=|$)", " ", scene.image_prompt).strip()
    match = re.search(r"\[ZR-SEED=(\d+)\]", prompt)
    old_seed = int(match.group(1)) if match else (scene.seed or (scene.index * 104729 + 17))
    new_seed = (old_seed + 524_287 * attempt + 7_919 * scene.index) % 2_147_483_647
    if new_seed <= 0:
        new_seed = scene.index + attempt + 1
    if match:
        prompt = prompt[:match.start()] + prompt[match.end():]
    scene.seed = new_seed
    return (
        prompt.rstrip()
        + f" Quality retry {attempt}: produce one coherent single full-frame cinematic shot. "
          "No montage, no contact sheet, no split screen, no frame-within-frame, no duplicate subject. "
          "Use a clearly different camera composition from the previous scene. "
        + f"[ZR-SEED={new_seed}]"
    )


def keyword_for_phrase(text: str) -> str:
    words = re.findall(r"[A-Za-z0-9][A-Za-z0-9'’-]*", text)
    candidates = [word for word in words if word.lower() not in STOPWORDS and len(word) >= 4]
    return max(candidates, key=len) if candidates else (words[-1] if words else "")
