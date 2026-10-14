from __future__ import annotations

from pathlib import Path
import math
import re
import shutil
import subprocess

from PySide6.QtGui import QImage

from .config import Settings
from .models import Scene
from .v060_story import quality_retry_prompt, scene_quality_report


def _gray(path: str | Path, size: int = 72) -> tuple[list[int], int, int] | None:
    image = QImage(str(path))
    if image.isNull() or image.width() < 24 or image.height() < 24:
        return None
    image = image.convertToFormat(QImage.Format_Grayscale8).scaled(size, size)
    values = [image.pixelColor(x, y).red() for y in range(image.height()) for x in range(image.width())]
    return values, image.width(), image.height()


def composition_signature(path: str | Path) -> str:
    sample = _gray(path, 72)
    if not sample:
        return ""
    values, w, h = sample
    cells: list[int] = []
    for gy in range(3):
        for gx in range(3):
            x0, x1 = gx * w // 3, (gx + 1) * w // 3
            y0, y1 = gy * h // 3, (gy + 1) * h // 3
            region = [values[y * w + x] for y in range(y0, y1) for x in range(x0, x1)]
            cells.append(int(round(sum(region) / max(1, len(region)))))
    return ",".join(str(value) for value in cells)


def _signature_distance(a: str, b: str) -> float:
    try:
        av = [int(v) for v in a.split(",")]
        bv = [int(v) for v in b.split(",")]
    except Exception:
        return 999.0
    if len(av) != 9 or len(bv) != 9:
        return 999.0
    return math.sqrt(sum((x - y) ** 2 for x, y in zip(av, bv)) / 9.0)


def _panel_score(path: str | Path) -> tuple[int, list[str]]:
    sample = _gray(path, 72)
    if not sample:
        return 0, []
    values, w, h = sample
    edges: list[int] = []
    for y in range(h):
        for x in range(w - 1):
            edges.append(abs(values[y * w + x + 1] - values[y * w + x]))
    for y in range(h - 1):
        for x in range(w):
            edges.append(abs(values[(y + 1) * w + x] - values[y * w + x]))
    baseline = max(1.0, sum(edges) / max(1, len(edges)))

    seams: list[float] = []
    for frac in (1 / 3, 1 / 2, 2 / 3):
        x = min(w - 1, max(1, int(round(w * frac))))
        v = sum(abs(values[y * w + x] - values[y * w + x - 1]) for y in range(h)) / h
        seams.append(v / baseline)
        y = min(h - 1, max(1, int(round(h * frac))))
        q = sum(abs(values[y * w + x2] - values[(y - 1) * w + x2]) for x2 in range(w)) / w
        seams.append(q / baseline)
    strong = sum(1 for ratio in seams if ratio >= 4.3)
    if strong >= 2:
        return 36, ["multi-panel/contact-sheet geometry detected"]
    if strong == 1 and max(seams, default=0) >= 6.2:
        return 22, ["strong inset/split-frame seam detected"]
    return 0, []


def _tesseract_path(settings: Settings) -> str | None:
    if settings.ocr_exe:
        path = Path(settings.ocr_exe).expanduser()
        if path.exists():
            return str(path)
    direct = shutil.which("tesseract")
    if direct:
        return direct
    common = Path("C:/Program Files/Tesseract-OCR/tesseract.exe")
    return str(common) if common.exists() else None


def readable_text(path: str | Path, settings: Settings) -> str:
    exe = _tesseract_path(settings)
    if not exe:
        return ""
    try:
        proc = subprocess.run(
            [exe, str(Path(path).resolve()), "stdout", "--psm", "11"],
            stdout=subprocess.PIPE,
            stderr=subprocess.DEVNULL,
            text=True,
            timeout=15,
        )
        if proc.returncode != 0:
            return ""
        value = " ".join(proc.stdout.split())
        # Ignore isolated OCR noise; flag only text that a viewer could plausibly notice.
        tokens = re.findall(r"[A-Za-z0-9]{2,}", value)
        return " ".join(tokens[:12]) if len(tokens) >= 2 else ""
    except Exception:
        return ""


def visual_qa_v2(
    path: str | Path,
    scene: Scene,
    settings: Settings,
    previous: Scene | None = None,
    previous2: Scene | None = None,
    ocr_guard: bool = True,
) -> tuple[int, list[str], bool]:
    score, notes, accepted = scene_quality_report(path, previous.image_path if previous else None)
    notes = [note for note in notes if note != "visual checks passed"]

    panel_penalty, panel_notes = _panel_score(path)
    score -= panel_penalty
    notes.extend(panel_notes)

    signature = composition_signature(path)
    scene.composition_signature = signature
    if previous and signature and previous.composition_signature:
        distance = _signature_distance(signature, previous.composition_signature)
        if distance < 7.5:
            score -= 24
            notes.append("composition too similar to previous scene")
    if previous2 and signature and previous2.composition_signature:
        distance2 = _signature_distance(signature, previous2.composition_signature)
        if distance2 < 6.0:
            score -= 12
            notes.append("composition repeats a recent visual pattern")

    if ocr_guard:
        text = readable_text(path, settings)
        scene.ocr_text = text
        if text:
            score -= 32
            notes.append(f"readable generated text detected: {text[:60]}")

    score = max(0, min(100, int(round(score))))
    hard_fail = any(
        key in note
        for note in notes
        for key in ("near-duplicate", "multi-panel", "readable generated text")
    )
    accepted = bool(score >= 62 and not hard_fail)
    if not notes:
        notes = ["Visual QA v2 passed"]
    return score, notes, accepted


def quality_retry_prompt_v2(scene: Scene, attempt: int) -> str:
    prompt = quality_retry_prompt(scene, attempt)
    extra = (
        " Visual QA retry: one photographic/cinematic frame only. No collage, no inset panels, no split screen, "
        "no poster layout, no duplicated person. Change subject scale and camera position clearly from neighboring shots. "
        "Avoid documents, labels, badges, screens, maps or signs facing camera. If one is narratively necessary, "
        "keep it distant, turned away, closed, out of focus, or otherwise unreadable; absolutely no legible letters or numbers."
    )
    marker = re.search(r"\[ZR-SEED=\d+\]\s*$", prompt)
    if marker:
        return prompt[:marker.start()].rstrip() + extra + " " + marker.group(0)
    return prompt + extra
