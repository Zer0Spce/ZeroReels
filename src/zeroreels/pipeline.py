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
    KokoroVoiceService,
    ScriptService,
    diagnostics,
)


def slugify(text: str) -> str:
    value = re.sub(r"[^a-zA-Z0-9]+", "-", text.strip()).strip("-").lower()
    return value[:55] or "reel"


class Pipeline:
    def __init__(self, settings: Settings):
        self.settings = settings

    def _preflight(self) -> None:
        rows = diagnostics(self.settings)
        required = {
            "Ollama", "Script model", "ComfyUI", "FLUX.2 nodes", "FLUX.2 model",
            "FLUX.2 text encoder", "FLUX.2 VAE", "Kokoro", "Voice model", "Voice pack", "FFmpeg",
        }
        failed = [label for label, ok, _ in rows if label in required and not ok]
        if failed:
            raise RuntimeError(
                "Real generation is not ready yet. Open Setup and complete the missing items:\n• "
                + "\n• ".join(failed)
            )

    def run(self, project: Project, options: GenerationOptions, progress=lambda value, text: None) -> Project:
        if not options.mock_mode:
            progress(2, "Checking local AI setup")
            self._preflight()

        stamp = time.strftime("%Y%m%d-%H%M%S")
        out_dir = PROJECTS_DIR / f"{stamp}-{slugify(project.topic)}"
        out_dir.mkdir(parents=True, exist_ok=True)
        project.output_dir = str(out_dir)

        progress(6, "Writing script and planning scenes")
        script_service = MockScriptService() if options.mock_mode else ScriptService(self.settings)
        project.script, project.scenes = script_service.generate(project, options.scene_count)
        if not project.title or project.title == "Untitled Reel":
            project.title = project.topic.strip()[:100] or "Untitled Reel"
        project.save(out_dir / "project.json")

        image_service = MockImageService() if options.mock_mode else ComfyImageService(self.settings)
        count = len(project.scenes)
        for i, scene in enumerate(project.scenes):
            pct = 14 + int(45 * (i / max(1, count)))
            progress(pct, f"Generating image {i + 1} of {count}")
            image = image_service.generate(scene, out_dir, project.format)
            scene.image_path = str(image)
            scene.status = "image-ready"
            project.save(out_dir / "project.json")

        progress(62, "Generating voice-over")
        voice_service = MockVoiceService() if options.mock_mode else KokoroVoiceService(self.settings)
        audio = voice_service.generate(project, out_dir, progress=progress)
        project.narration_path = str(audio)
        project.save(out_dir / "project.json")

        captions = None
        if options.captions:
            progress(76, "Creating timed captions")
            captions = CaptionService().generate_from_scenes(project, out_dir)
            project.captions_path = str(captions)

        progress(84, "Rendering final video")
        video, burned = FFmpegRenderer(self.settings).render(
            project,
            audio,
            captions,
            out_dir,
            motion=options.motion,
            transitions=options.transitions,
        )
        project.video_path = str(video)
        project.captions_burned = burned
        project.save(out_dir / "project.json")
        progress(100, "Video ready")
        return project
