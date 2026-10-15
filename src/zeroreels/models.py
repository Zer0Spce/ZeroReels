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
    ocr_text: str = ""
    composition_signature: str = ""
    director_note: str = ""
    source_type: str = "AI Generated"
    source_url: str = ""
    source_credit: str = ""
    source_license: str = ""
    source_query: str = ""
    media_type: str = "image"
    overlay_video_path: str = ""
    overlay_source_url: str = ""
    overlay_source_credit: str = ""
    overlay_source_license: str = ""
    overlay_source_query: str = ""


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
    voice_engine_used: str = ""
    voice_delivery: str = ""
    runtime_rewrites: int = 0
    visual_qa_summary: str = ""
    image_source_mode: str = "AI Generated"
    web_video_broll: bool = False
    web_video_overlay: bool = False
    research_context: str = ""
    research_source: str = ""
    script_mode: str = "AI Script"
    custom_script: str = ""
    script_model_mode: str = "Auto Quality"
    script_model_used: str = ""
    script_quality_summary: str = ""

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
    soundtrack_mode: str = "Smart Soundscape"
    sfx: bool = True
    quality_guard: bool = True
    quality_retries: int = 2
    voice_engine: str = "Kokoro Directed"
    voice_delivery: str = "Natural Storyteller"
    runtime_lock: bool = True
    visual_qa_v2: bool = True
    ocr_guard: bool = True
    dynamic_visual_pacing: bool = True
    image_source_mode: str = "AI Generated"
    web_video_broll: bool = True
    web_video_overlay: bool = True
    research_grounding: bool = False
    script_mode: str = "AI Script"
    script_model_mode: str = "Auto Quality"
