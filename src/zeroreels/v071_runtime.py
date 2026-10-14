from __future__ import annotations

import json
import re

from . import services
from .config import Settings
from .models import Project


def _words(text: str) -> int:
    return len(re.findall(r"\b[\w’'-]+\b", text or ""))


def rewrite_for_measured_duration_v2(
    settings: Settings,
    project: Project,
    actual_seconds: float,
    progress=None,
    pass_index: int = 1,
) -> bool:
    target = float(project.target_seconds)
    if target <= 0 or actual_seconds <= 0:
        return False
    ratio = target / actual_seconds
    if 0.95 <= ratio <= 1.05:
        return False

    scene_count = len(project.scenes)
    if scene_count <= 0:
        return False
    current_words = sum(_words(scene.narration) for scene in project.scenes)
    target_words = max(scene_count * 5, round(current_words * ratio))
    low = max(scene_count * 4, round(target_words * 0.96))
    high = max(low + 1, round(target_words * 1.04))
    if progress:
        progress(31, f"Runtime Lock v2 pass {pass_index} • {actual_seconds:.1f}s → {target:.0f}s • words {current_words} → {low}-{high}")

    schema = {
        "type": "object",
        "properties": {
            "scenes": {
                "type": "array",
                "minItems": scene_count,
                "maxItems": scene_count,
                "items": {
                    "type": "object",
                    "properties": {"narration": {"type": "string"}},
                    "required": ["narration"],
                },
            }
        },
        "required": ["scenes"],
    }
    draft = "\n".join(f"{i + 1}. {scene.narration}" for i, scene in enumerate(project.scenes))
    research = (project.research_context or "").strip()[:2600]
    research_block = f"\nVERIFIED CONTEXT YOU MAY USE:\n{research}\n" if research else ""
    direction = "expand" if actual_seconds < target else "tighten"
    prompt = f"""You are a precision spoken-runtime editor for a short-form narration.

TOPIC: {project.topic}
STYLE: {project.style}
MEASURED AUDIO: {actual_seconds:.2f} seconds
TARGET AUDIO: {target:.2f} seconds
CURRENT TOTAL WORDS: {current_words}
REQUIRED TOTAL WORDS: between {low} and {high}
SCENES: exactly {scene_count}
TASK: {direction} the narration so the NEXT real TTS pass lands near the target.
{research_block}
Rules:
- Hit the required TOTAL WORD RANGE. This is a hard production constraint.
- Keep exactly {scene_count} scene entries and preserve their order/purpose.
- Preserve names, numbers, uncertainty and causal meaning.
- Use verified context only when expanding factual material. If no context supports a detail, explain the existing idea more clearly instead of inventing facts.
- Natural spoken English: contractions, varied sentence length, occasional short punchy lines.
- No repeated ideas, filler, generic hype, essay phrasing or CTA.
- Scene 1 hooks immediately. Final scene ends on one memorable natural line.
- Return ONLY JSON matching the schema.

DRAFT:\n{draft}"""
    try:
        result = services._post_json(
            settings.ollama_url.rstrip("/") + "/api/generate",
            {
                "model": settings.ollama_model,
                "prompt": prompt,
                "stream": False,
                "format": schema,
                "think": False,
                "options": {"temperature": 0.30, "top_p": 0.88, "repeat_penalty": 1.14},
            },
            timeout=600,
        )
        data = json.loads(result["response"])
        rows = data.get("scenes", [])
        if len(rows) != scene_count:
            return False
        values = [" ".join(str(row.get("narration", "")).split()).strip() for row in rows]
        if not all(values):
            return False
        produced_words = sum(_words(value) for value in values)
        # Reject extreme misses; another vague rewrite is worse than keeping the usable take.
        if produced_words < max(scene_count * 4, round(target_words * 0.72)) or produced_words > round(target_words * 1.28):
            if progress:
                progress(32, f"Runtime Lock v2 rejected weak rewrite • {produced_words} words")
            return False
        for scene, text in zip(project.scenes, values):
            scene.narration = text
        project.script = " ".join(values)
        project.runtime_rewrites += 1
        if progress:
            progress(32, f"Runtime Lock v2 rewrite ready • {produced_words} words • re-performing narration")
        return True
    except Exception:
        if progress:
            progress(32, "Runtime Lock v2 rewrite unavailable • keeping usable narration")
        return False
