from __future__ import annotations

import re

from . import services


def install() -> None:
    original_generate = services.ScriptService.generate

    def generate(self, project, scene_count: int):
        script, scenes = original_generate(self, project, scene_count)
        for scene in scenes:
            matches = re.findall(r"\[ZR-SEED=(\d+)\]", scene.image_prompt)
            seed = int(matches[-1]) if matches else scene.seed
            base = re.sub(r"\s*\[ZR-SEED=\d+\]\s*", " ", scene.image_prompt).strip()
            base += (
                " Caption-safe framing: keep faces, hands and the key story object comfortably inside frame edges; "
                "leave the lower caption band visually quiet when possible; avoid cropping through eyes, mouths, hands or the main prop."
            )
            if seed:
                scene.seed = seed
                base += f" [ZR-SEED={seed}]"
            scene.image_prompt = base
        return script, scenes

    services.ScriptService.generate = generate
