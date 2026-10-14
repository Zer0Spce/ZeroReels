from __future__ import annotations

from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any
import json
import time


@dataclass(slots=True)
class Scene:
    index: int
    narration: str
    image_prompt: str
    duration: float = 4.0
    image_path: str = ""
    audio_path: str = ""
    status: str = "pending"
    reuse_previous_image: bool = False
    shot_role: str = ""
    quality_score: int = 0
    quality_notes: list[str] = field(default_factory=list)
    retry_count: int = 0
    seed: int = 0
    motion_style: str = ""
    transition_to_next: str = ""


@dataclass(slots=True)
class Project:
    topic: str
    title: str = "Untitled Reel"
    format: str = "9:16"
    style: str = "Cinematic Documentary"
    voice: str = "Default"
    target_seconds: int = 60
    continuity_mode: str = "Consistent Story"
    script: str = ""
    scenes: list[Scene] = field(default_factory=list)
    created_at: float = field(default_factory=time.time)
    output_dir: str = ""
    video_path: str = ""
    narration_path: str = ""
    captions_path: str = ""
    captions_burned: bool = False
    actual_seconds: float = 0.0
    soundtrack_used: str = ""
    quality_summary: str = ""

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    def save(self, path: str | Path) -> Path:
        target = Path(path)
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(json.dumps(self.to_dict(), indent=2, ensure_ascii=False), encoding="utf-8")
        return target

    @classmethod
    def load(cls, path: str | Path) -> "Project":
        data = json.loads(Path(path).read_text(encoding="utf-8"))
        data["scenes"] = [Scene(**scene) for scene in data.get("scenes", [])]
        return cls(**data)


@dataclass(slots=True)
class GenerationOptions:
    mock_mode: bool = False
    full_auto: bool = True
    captions: bool = True
    music: bool = True
    motion: bool = True
    transitions: bool = True
    scene_count: int = 8
    caption_position: str = "Bottom"
    caption_size: str = "Small"
    caption_style: str = "TikTok Pop"
    transition_style: str = "Story Rhythm"
    soundtrack_mode: str = "Auto Ambience"
    sfx: bool = True
    quality_guard: bool = True
    quality_retries: int = 2
