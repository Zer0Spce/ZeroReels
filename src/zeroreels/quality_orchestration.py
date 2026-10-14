from __future__ import annotations

import json
import re

from . import services


def _plan_visual_reuse(self, project, scene_count: int, original_generate):
    script, scenes = original_generate(self, project, scene_count)
    mode = getattr(project, "continuity_mode", "Consistent Story")
    if mode == "Independent Shots" or len(scenes) < 2:
        return script, scenes

    schema = {
        "type": "object",
        "properties": {
            "scenes": {
                "type": "array",
                "minItems": len(scenes),
                "maxItems": len(scenes),
                "items": {
                    "type": "object",
                    "properties": {"reuse_previous_image": {"type": "boolean"}},
                    "required": ["reuse_previous_image"],
                },
            }
        },
        "required": ["scenes"],
    }
    storyboard = []
    for scene in scenes:
        prompt_preview = re.sub(r"\s*\[ZR-SEED=\d+\]\s*$", "", scene.image_prompt).strip()
        storyboard.append(
            f"SCENE {scene.index}\nNARRATION: {scene.narration}\nVISUAL: {prompt_preview[:700]}"
        )
    prompt = f"""You are editing a short video storyboard for visual continuity.
Continuity mode: {mode}

For each scene, decide whether it should REUSE THE PREVIOUS SCENE'S EXACT GENERATED IMAGE, with only a different camera crop/motion in the edit.

Rules:
- Scene 1 must always be false.
- Reuse only when the narration is clearly continuing the same exact moment, subject, and location and a brand-new generated image would feel like an unnecessary visual reset.
- Do not reuse merely because the same character appears later; different actions, times, locations, or important visual evidence deserve a fresh image.
- Reuse is a deliberate editing tool, not the default. For a typical 8-scene reel, about 1-2 reuses is usually enough; 0 is valid if every beat needs a fresh shot.
- Avoid reusing more than two scenes in a row.
- In Same Cast & World mode you may reuse slightly more often, but still preserve meaningful visual progression.
- Never change narration or add facts. Return only the reuse decisions.

STORYBOARD:\n""" + "\n\n".join(storyboard)
    try:
        result = services._post_json(
            self.settings.ollama_url.rstrip("/") + "/api/generate",
            {
                "model": self.settings.ollama_model,
                "prompt": prompt,
                "stream": False,
                "format": schema,
                "think": False,
                "options": {"temperature": 0.08},
            },
            timeout=300,
        )
        data = json.loads(result["response"])
        decisions = data.get("scenes", [])
        if len(decisions) == len(scenes):
            for i, (scene, decision) in enumerate(zip(scenes, decisions)):
                scene.reuse_previous_image = bool(decision.get("reuse_previous_image", False)) if i > 0 else False
    except Exception:
        # Reuse planning is optional; fresh generation remains a valid fallback.
        pass
    return script, scenes


def _calibrated_voice(self, project, out_dir, progress, original_generate):
    words = sum(len(re.findall(r"\b[\w’'-]+\b", scene.narration)) for scene in project.scenes)
    pauses = max(0, len(project.scenes) - 1) * 0.18
    target_spoken = max(5.0, float(project.target_seconds) - pauses)
    estimated_natural = words / 2.35 if words else target_spoken
    timing_factor = estimated_natural / target_spoken
    # Keep the narrator natural. This gently corrects large duration misses without chipmunk/slow-motion speech.
    timing_factor = max(0.90, min(1.10, timing_factor))
    original_speed = float(self.settings.kokoro_speed)
    calibrated = max(0.78, min(1.22, original_speed * timing_factor))
    if progress:
        progress(63, f"Calibrating narration pace • {words} words • target {project.target_seconds}s")
    self.settings.kokoro_speed = calibrated
    try:
        return original_generate(self, project, out_dir, progress=progress)
    finally:
        self.settings.kokoro_speed = original_speed


def install() -> None:
    original_script_generate = services.ScriptService.generate
    original_voice_generate = services.KokoroVoiceService.generate

    def script_generate(self, project, scene_count: int):
        return _plan_visual_reuse(self, project, scene_count, original_script_generate)

    def voice_generate(self, project, out_dir, progress=None):
        return _calibrated_voice(self, project, out_dir, progress, original_voice_generate)

    services.ScriptService.generate = script_generate
    services.KokoroVoiceService.generate = voice_generate
