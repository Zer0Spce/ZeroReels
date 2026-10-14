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
        progress(1, "Initializing local pipeline")
        if not options.mock_mode:
            progress(2, "Checking local AI setup")
            self._preflight()
            progress(4, "Local AI setup ready")

        stamp = time.strftime("%Y%m%d-%H%M%S")
        out_dir = PROJECTS_DIR / f"{stamp}-{slugify(project.topic)}"
        out_dir.mkdir(parents=True, exist_ok=True)
        project.output_dir = str(out_dir)
        progress(5, "Project workspace ready")

        script_service = MockScriptService() if options.mock_mode else ScriptService(self.settings)
        # Real ScriptService uses this callback for sub-stage events in v0.5.3.
        try:
            script_service._zr_progress = progress
        except Exception:
            pass
        progress(6, "Writing short-form narration")
        project.script, project.scenes = script_service.generate(project, options.scene_count)
        if not project.title or project.title == "Untitled Reel":
            project.title = project.topic.strip()[:100] or "Untitled Reel"
        project.save(out_dir / "project.json")
        progress(14, "Story plan saved • generating visuals")

        image_service = MockImageService() if options.mock_mode else ComfyImageService(self.settings)
        count = len(project.scenes)
        image_span = 44
        for i, scene in enumerate(project.scenes):
            start_pct = 15 + int(image_span * (i / max(1, count)))
            end_pct = 15 + int(image_span * ((i + 1) / max(1, count)))
            progress(start_pct, f"Generating image {i + 1} of {count}")
            # v0.5.3 intentionally always generates a fresh visual. Continuity controls
            # identity/world consistency in the prompt; it never reuses the previous file.
            scene.reuse_previous_image = False
            image = image_service.generate(scene, out_dir, project.format)
            scene.image_path = str(image)
            scene.status = "image-ready"
            project.save(out_dir / "project.json")
            progress(max(start_pct + 1, end_pct - 1), f"Image {i + 1} of {count} ready")

        progress(60, "All visuals ready • preparing narration")
        voice_service = MockVoiceService() if options.mock_mode else KokoroVoiceService(self.settings)
        audio = voice_service.generate(project, out_dir, progress=progress)
        project.narration_path = str(audio)
        project.save(out_dir / "project.json")
        progress(75, "Narration ready")

        captions = None
        if options.captions:
            progress(77, "Building phrase-timed captions")
            captions = CaptionService().generate_from_scenes(project, out_dir)
            project.captions_path = str(captions)
            progress(80, "Captions ready")
        else:
            progress(80, "Captions disabled")

        progress(83, "Preparing motion and transition edit")
        renderer = FFmpegRenderer(self.settings)
        try:
            renderer._zr_progress = progress
        except Exception:
            pass
        video, burned = renderer.render(
            project,
            audio,
            captions,
            out_dir,
            motion=options.motion,
            transitions=options.transitions,
            caption_position=options.caption_position,
            caption_size=options.caption_size,
            transition_style=options.transition_style,
        )
        project.video_path = str(video)
        project.captions_burned = burned
        project.save(out_dir / "project.json")
        progress(98, "Final MP4 written")
        progress(100, "Video ready")
        return project
