from __future__ import annotations

import json
import re

from . import services
from .v053_quality import _too_repetitive


def _word_count(text: str) -> int:
    return len(re.findall(r"\b[\w’'-]+\b", text or ""))


def _generic_hook(text: str) -> bool:
    value = " ".join((text or "").lower().split())
    return value.startswith((
        "imagine this",
        "did you know",
        "have you ever wondered",
        "in a world where",
        "picture this",
        "today we're going to",
        "in this video",
    ))


def install() -> None:
    original_generate = services.ScriptService.generate

    def generate(self, project, scene_count: int):
        script, scenes = original_generate(self, project, scene_count)
        target_words = max(28, round(project.target_seconds * 2.45))
        current_words = sum(_word_count(scene.narration) for scene in scenes)
        needs_length = current_words < target_words * 0.80 or current_words > target_words * 1.20
        needs_hook = bool(scenes and _generic_hook(scenes[0].narration))
        if not (needs_length or needs_hook):
            return script, scenes

        callback = getattr(self, "_zr_progress", None)
        if callback:
            callback(13, f"Balancing narration length • {current_words} words → target ~{target_words}")

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
        draft = "\n".join(f"{i + 1}. {scene.narration}" for i, scene in enumerate(scenes))
        prompt = f"""Tighten this finished short-form narration for timing and natural delivery.

TOPIC: {project.topic}
TARGET: about {target_words} spoken words total, preferably within 10 percent
SCENES: exactly {scene_count}

Rules:
- Rewrite narration only. Preserve the existing facts and meaning. Add no new facts, numbers, dates, names, quotes, studies or events.
- Keep every scene as a distinct next story beat.
- Keep the opening immediate and specific; do not begin with 'Imagine this', 'Did you know', 'Have you ever wondered', 'Picture this', or production language.
- Sound conversational and spoken, not like an essay.
- Use contractions naturally and vary sentence length.
- If shortening, remove filler/redundancy before removing meaningful information.
- If expanding, clarify an existing idea rather than inventing a new claim.
- Keep the final line concise and memorable; no CTA.
- Return ONLY JSON matching the schema.

DRAFT:\n{draft}"""
        old = [scene.narration for scene in scenes]
        try:
            result = services._post_json(
                self.settings.ollama_url.rstrip("/") + "/api/generate",
                {
                    "model": self.settings.ollama_model,
                    "prompt": prompt,
                    "stream": False,
                    "format": schema,
                    "think": False,
                    "options": {"temperature": 0.34, "top_p": 0.9, "repeat_penalty": 1.1},
                },
                timeout=600,
            )
            data = json.loads(result["response"])
            edited = data.get("scenes", [])
            if len(edited) == scene_count:
                values = [" ".join(str(item.get("narration", "")).split()).strip() for item in edited]
                if all(values):
                    for scene, value in zip(scenes, values):
                        scene.narration = value
                    revised_words = sum(_word_count(scene.narration) for scene in scenes)
                    if _too_repetitive(scenes) or revised_words < target_words * 0.70 or revised_words > target_words * 1.35:
                        for scene, value in zip(scenes, old):
                            scene.narration = value
                    elif callback:
                        callback(13, f"Narration timing balanced • {revised_words} words")
        except Exception:
            for scene, value in zip(scenes, old):
                scene.narration = value

        return " ".join(scene.narration for scene in scenes).strip(), scenes

    services.ScriptService.generate = generate
