from __future__ import annotations

from pathlib import Path
import re
import time

from .config import PROJECTS_DIR, Settings
from .models import GenerationOptions, Project
from .services import (
    CaptionService,
    ComfyImageService,
    FFmpegRenderer,
    MockImageService,
    MockScriptService,
    MockVoiceService,
    PiperVoiceService,
    ScriptService,
)


def slugify(text: str) -> str:
    value = re.sub(r"[^a-zA-Z0-9]+", "-", text.strip()).strip("-").lower()
    return value[:55] or "reel"


class Pipeline:
    def __init__(self, settings: Settings):
        self.settings = settings

    def run(self, project: Project, options: GenerationOptions, progress=lambda value, text: None) -> Project:
        stamp = time.strftime("%Y%m%d-%H%M%S")
        out_dir = PROJECTS_DIR / f"{stamp}-{slugify(project.topic)}"
        out_dir.mkdir(parents=True, exist_ok=True)
        project.output_dir = str(out_dir)

        progress(5, "Writing script and planning scenes")
        script_service = MockScriptService() if options.mock_mode else ScriptService(self.settings)
        project.script, project.scenes = script_service.generate(project, options.scene_count)
        project.title = project.topic.strip()[:80] or "Untitled Reel"
        project.save(out_dir / "project.json")

        image_service = MockImageService() if options.mock_mode else ComfyImageService(self.settings)
        count = len(project.scenes)
        for i, scene in enumerate(project.scenes):
            pct = 12 + int(48 * (i / max(1, count)))
            progress(pct, f"Generating scene {i + 1} of {count}")
            image = image_service.generate(scene, out_dir, project.format)
            scene.image_path = str(image)
            scene.status = "ready"
            project.save(out_dir / "project.json")

        progress(63, "Generating voice-over")
        voice_service = MockVoiceService() if options.mock_mode else PiperVoiceService(self.settings)
        audio = voice_service.generate(project, out_dir)

        progress(74, "Creating captions")
        captions = CaptionService().generate_from_scenes(project, out_dir) if options.captions else None

        progress(84, "Rendering video")
        video = FFmpegRenderer(self.settings).render(project, audio, captions, out_dir, motion=options.motion)
        project.video_path = str(video)
        project.save(out_dir / "project.json")
        progress(100, "Finished")
        return project
