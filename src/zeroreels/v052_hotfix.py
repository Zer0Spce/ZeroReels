from __future__ import annotations

from difflib import SequenceMatcher
import json
import re
import time

from PySide6.QtCore import QTimer
from PySide6.QtWidgets import QLabel

from . import services, ui


_SEED_RE = re.compile(r"\s*\[ZR-SEED=(\d+)\]\s*$")
_SHOT_VARIATIONS = (
    "wide establishing composition with strong environmental context",
    "medium three-quarter composition with a clearly different camera position",
    "close detail composition focused on a meaningful object or expression",
    "profile or side-angle medium shot with layered foreground and background",
    "high-angle or overhead-inspired composition with a clearly changed framing",
    "low-angle environmental composition with a clearly changed perspective",
    "rear three-quarter composition looking into the environment",
    "wide atmospheric composition with subject placed differently in frame",
)


def _normalized(text: str) -> str:
    return " ".join(re.findall(r"[a-z0-9']+", (text or "").lower()))


def _similarity(a: str, b: str) -> float:
    na, nb = _normalized(a), _normalized(b)
    if not na or not nb:
        return 0.0
    return SequenceMatcher(None, na, nb).ratio()


def _narration_too_repetitive(scenes) -> bool:
    values = [_normalized(scene.narration) for scene in scenes]
    nonempty = [value for value in values if value]
    if len(nonempty) != len(values):
        return True
    if len(set(nonempty)) != len(nonempty):
        return True
    for i in range(1, len(values)):
        if _similarity(values[i - 1], values[i]) >= 0.74:
            return True
    # Catch a repeated template even when duplicates are not adjacent.
    for i in range(len(values)):
        for j in range(i + 2, len(values)):
            if _similarity(values[i], values[j]) >= 0.82:
                return True
    return False


def _repair_narration(script_service, project, scenes) -> bool:
    """Repair a collapsed/repetitive scene plan without changing the visual plan."""
    scene_count = len(scenes)
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

    storyboard = []
    for scene in scenes:
        visual = _SEED_RE.sub("", scene.image_prompt or "").strip()
        storyboard.append(
            f"SCENE {scene.index}\nCURRENT NARRATION: {scene.narration}\nVISUAL INTENT: {visual[:900]}"
        )

    prompt = f"""You are repairing a short-form narration that accidentally repeats the same beat across scenes.

TOPIC: {project.topic}
TARGET: {project.target_seconds} seconds
SCENES: exactly {scene_count}

Rewrite ONLY the narration fields.

Hard rules:
- Every scene must advance the story with a distinct idea or next beat.
- Never repeat or lightly paraphrase a previous scene's sentence.
- Do not repeat a clause longer than about 6 words across scenes unless it is an unavoidable proper name.
- Preserve facts already present; do not invent new dates, quotes, statistics, official findings, or events.
- Keep the narration natural and spoken, with varied sentence length and transitions.
- The sequence must have a clear progression: hook -> development -> consequence/context -> landing.
- Use the visual intent only to understand what each scene is trying to show; do not describe the camera or say 'scene'.
- Keep approximately the same total spoken length.
- Return only JSON matching the schema.

STORYBOARD:\n""" + "\n\n".join(storyboard)

    endpoint = script_service.settings.ollama_url.rstrip("/") + "/api/generate"
    for temperature in (0.42, 0.62):
        try:
            result = services._post_json(
                endpoint,
                {
                    "model": script_service.settings.ollama_model,
                    "prompt": prompt,
                    "stream": False,
                    "format": schema,
                    "think": False,
                    "options": {"temperature": temperature, "top_p": 0.9},
                },
                timeout=600,
            )
            data = json.loads(result["response"])
            repaired = data.get("scenes", [])
            if len(repaired) != scene_count:
                continue
            candidate = []
            for item in repaired:
                value = " ".join(str(item.get("narration", "")).split()).strip()
                if not value:
                    candidate = []
                    break
                candidate.append(value)
            if not candidate:
                continue

            old = [scene.narration for scene in scenes]
            for scene, value in zip(scenes, candidate):
                scene.narration = value
            if not _narration_too_repetitive(scenes):
                return True
            for scene, value in zip(scenes, old):
                scene.narration = value
        except Exception:
            continue
    return False


def _enforce_visual_diversity(project, scenes) -> None:
    """Continuity means a coherent cast/world, not recycling one generated frame."""
    mode = getattr(project, "continuity_mode", "Consistent Story")
    base_seed = None
    for scene in scenes:
        scene.reuse_previous_image = False
        match = _SEED_RE.search(scene.image_prompt or "")
        if match and base_seed is None:
            base_seed = int(match.group(1))

    for i, scene in enumerate(scenes):
        prompt = scene.image_prompt or ""
        match = _SEED_RE.search(prompt)
        marker = ""
        body = prompt
        if match:
            body = prompt[: match.start()].rstrip()
            seed = int(match.group(1))
            if mode == "Same Cast & World":
                # A deterministic seed family gives each shot fresh noise while keeping
                # the exact continuity bible and character description stable.
                root = base_seed if base_seed is not None else seed
                seed = (root + i * 104_729) % 2_147_483_647
                if seed <= 0:
                    seed = i + 1
            marker = f" [ZR-SEED={seed}]"

        variation = _SHOT_VARIATIONS[i % len(_SHOT_VARIATIONS)]
        # Add a shot-level composition constraint even if the local model tries to fall
        # back to the same framing. Do not alter story facts or continuity traits.
        body = body.rstrip(" .") + f". Distinct shot variation: {variation}."
        scene.image_prompt = body + marker


def _format_elapsed(seconds: float) -> str:
    seconds = max(0, int(seconds))
    return f"{seconds // 60:02d}:{seconds % 60:02d}"


def install() -> None:
    # Script/visual guard runs after the v0.5 quality/orchestration layers.
    original_script_generate = services.ScriptService.generate

    def script_generate(self, project, scene_count: int):
        script, scenes = original_script_generate(self, project, scene_count)
        _enforce_visual_diversity(project, scenes)
        if _narration_too_repetitive(scenes):
            repaired = _repair_narration(self, project, scenes)
            if not repaired:
                raise RuntimeError(
                    "The local script model produced repetitive scene narration twice. "
                    "ZeroReels stopped before wasting time on repeated images. Try Generate again."
                )
        script = " ".join(scene.narration for scene in scenes).strip()
        return script, scenes

    services.ScriptService.generate = script_generate

    original_sidebar = ui.MainWindow._sidebar
    original_generate = ui.MainWindow._generate
    original_progress = ui.MainWindow._on_progress
    original_complete = ui.MainWindow._on_complete
    original_failed = ui.MainWindow._on_failed
    original_create_page = ui.MainWindow._create_page

    def sidebar(self):
        frame = original_sidebar(self)
        for label in frame.findChildren(QLabel):
            if label.text() == "v0.5.1":
                label.setText("v0.5.2")
                label.setMaximumWidth(82)
        return frame

    def create_page(self):
        page = original_create_page(self)
        if hasattr(self, "continuity_box"):
            self.continuity_box.setToolTip(
                "Continuity keeps recurring people/world traits coherent. Every scene still generates a fresh image and composition."
            )
        return page

    def heartbeat(self):
        worker = getattr(self, "worker", None)
        timer = getattr(self, "_generation_heartbeat_timer", None)
        if not worker or not worker.isRunning():
            if timer:
                timer.stop()
            return
        started = getattr(self, "_generation_started_at", time.monotonic())
        elapsed = time.monotonic() - started
        stage = getattr(self, "_generation_stage", "Working")
        value = int(getattr(self, "_generation_progress_value", self.progress.value() if hasattr(self, "progress") else 0))
        if hasattr(self, "status_detail"):
            self.status_detail.setText(f"{value}% • {stage} • elapsed {_format_elapsed(elapsed)}")

        bucket = int(elapsed // 12)
        last_bucket = getattr(self, "_generation_heartbeat_bucket", -1)
        if bucket > 0 and bucket != last_bucket:
            self._generation_heartbeat_bucket = bucket
            if hasattr(self, "_append_create_log"):
                self._append_create_log(f"… still working • {stage} • elapsed {_format_elapsed(elapsed)}")

    def generate(self):
        self._generation_started_at = time.monotonic()
        self._generation_stage = "Preparing local pipeline"
        self._generation_progress_value = 1
        self._generation_heartbeat_bucket = -1
        result = original_generate(self)
        worker = getattr(self, "worker", None)
        if worker and worker.isRunning():
            if not hasattr(self, "_generation_heartbeat_timer"):
                self._generation_heartbeat_timer = QTimer(self)
                self._generation_heartbeat_timer.setInterval(1000)
                self._generation_heartbeat_timer.timeout.connect(lambda: heartbeat(self))
            self._generation_heartbeat_timer.start()
            if hasattr(self, "_append_create_log"):
                self._append_create_log("Pipeline worker started. Live status will update while local AI is busy.")
            heartbeat(self)
        return result

    def progress(self, value: int, text: str):
        self._generation_progress_value = int(value)
        self._generation_stage = str(text)
        result = original_progress(self, value, text)
        heartbeat(self)
        return result

    def complete(self, project):
        timer = getattr(self, "_generation_heartbeat_timer", None)
        if timer:
            timer.stop()
        return original_complete(self, project)

    def failed(self, message: str):
        timer = getattr(self, "_generation_heartbeat_timer", None)
        if timer:
            timer.stop()
        return original_failed(self, message)

    ui.MainWindow._sidebar = sidebar
    ui.MainWindow._create_page = create_page
    ui.MainWindow._generate = generate
    ui.MainWindow._on_progress = progress
    ui.MainWindow._on_complete = complete
    ui.MainWindow._on_failed = failed
