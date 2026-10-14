from __future__ import annotations

from pathlib import Path
import time

from . import pipeline, services
from .config import PROJECTS_DIR
from .models import GenerationOptions, Project
from .v060_story import professional_script_generate, quality_retry_prompt, scene_quality_report


def _quality_summary(project: Project) -> str:
    if not project.scenes:
        return "No scenes"
    retries = sum(scene.retry_count for scene in project.scenes)
    warnings = sum(1 for scene in project.scenes if scene.status == "image-warning")
    passed = len(project.scenes) - warnings
    if retries:
        return f"{passed}/{len(project.scenes)} scenes passed quality guard • {retries} regeneration(s)"
    return f"{passed}/{len(project.scenes)} scenes passed quality guard"


def professional_run(self, project: Project, options: GenerationOptions, progress=lambda value, text: None) -> Project:
    progress(1, "Initializing professional local pipeline")
    if not options.mock_mode:
        progress(2, "Checking local AI setup")
        self._preflight()
        progress(4, "Local AI setup ready")

    stamp = time.strftime("%Y%m%d-%H%M%S")
    out_dir = PROJECTS_DIR / f"{stamp}-{pipeline.slugify(project.topic)}"
    out_dir.mkdir(parents=True, exist_ok=True)
    project.output_dir = str(out_dir)
    progress(5, "Project workspace ready")

    script_service = services.MockScriptService() if options.mock_mode else services.ScriptService(self.settings)
    try:
        script_service._zr_progress = progress
    except Exception:
        pass
    progress(6, "Writing retention-first narration")
    project.script, project.scenes = script_service.generate(project, options.scene_count)
    if not project.title or project.title == "Untitled Reel":
        project.title = project.topic.strip()[:100] or "Untitled Reel"
    project.save(out_dir / "project.json")
    progress(14, "Story plan locked • generating directed visuals")

    image_service = services.MockImageService() if options.mock_mode else services.ComfyImageService(self.settings)
    count = len(project.scenes)
    image_span = 44
    for i, scene in enumerate(project.scenes):
        start_pct = 15 + int(image_span * (i / max(1, count)))
        end_pct = 15 + int(image_span * ((i + 1) / max(1, count)))
        previous_path = project.scenes[i - 1].image_path if i > 0 else None
        max_retries = 0 if options.mock_mode or not options.quality_guard else max(0, int(options.quality_retries))
        accepted = False
        last_image: Path | None = None

        for attempt in range(max_retries + 1):
            if attempt:
                scene.image_prompt = quality_retry_prompt(scene, attempt)
                progress(start_pct, f"Regenerating scene {i + 1}/{count} • quality retry {attempt}/{max_retries}")
            else:
                role = f" • {scene.shot_role}" if scene.shot_role else ""
                progress(start_pct, f"Generating scene {i + 1}/{count}{role}")

            last_image = image_service.generate(scene, out_dir, project.format)
            scene.image_path = str(last_image)

            if options.mock_mode or not options.quality_guard:
                scene.quality_score = 100
                scene.quality_notes = ["quality guard skipped"]
                accepted = True
            else:
                score, notes, accepted = scene_quality_report(last_image, previous_path)
                scene.quality_score = score
                scene.quality_notes = notes
                if not accepted and attempt < max_retries:
                    reason = notes[0] if notes else "weak visual"
                    progress(start_pct, f"Scene {i + 1} quality {score}/100 • {reason} • retrying")

            scene.retry_count = attempt
            if accepted:
                break

        if last_image is None:
            raise RuntimeError(f"Scene {i + 1} did not produce an image")

        if accepted:
            scene.status = "image-ready"
            progress(max(start_pct + 1, end_pct - 1), f"Scene {i + 1}/{count} accepted • quality {scene.quality_score}/100")
        else:
            scene.status = "image-warning"
            note = scene.quality_notes[0] if scene.quality_notes else "quality warning"
            progress(max(start_pct + 1, end_pct - 1), f"Scene {i + 1}/{count} kept after retries • {note}")
        project.save(out_dir / "project.json")

    project.quality_summary = _quality_summary(project)
    progress(60, project.quality_summary)

    voice_service = services.MockVoiceService() if options.mock_mode else services.KokoroVoiceService(self.settings)
    progress(61, "Generating humanized narration")
    audio = voice_service.generate(project, out_dir, progress=progress)
    project.narration_path = str(audio)
    project.actual_seconds = round(sum(max(0.0, scene.duration) for scene in project.scenes), 2)
    drift = project.actual_seconds - float(project.target_seconds)
    if abs(drift) >= max(3.0, project.target_seconds * 0.10):
        progress(75, f"Narration ready • {project.actual_seconds:.1f}s actual vs {project.target_seconds}s target")
    else:
        progress(75, f"Narration timing locked • {project.actual_seconds:.1f}s")
    project.save(out_dir / "project.json")

    captions = None
    if options.captions:
        progress(77, f"Building {options.caption_style} captions")
        caption_service = services.CaptionService()
        caption_service._zr_caption_style = options.caption_style
        caption_service._zr_caption_position = options.caption_position
        caption_service._zr_caption_size = options.caption_size
        captions = caption_service.generate_from_scenes(project, out_dir)
        project.captions_path = str(captions)
        progress(80, "Professional captions ready")
    else:
        progress(80, "Captions disabled")

    progress(82, "Planning motion, cuts and final grade")
    renderer = services.FFmpegRenderer(self.settings)
    renderer._zr_progress = progress
    renderer._zr_caption_style = options.caption_style
    renderer._zr_caption_filename = Path(captions).name if captions else ""
    renderer._zr_soundtrack_mode = options.soundtrack_mode if options.music else "Off"
    renderer._zr_sfx = bool(options.sfx)
    renderer._zr_project = project

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
    progress(98, "Professional edit finalized")
    progress(100, "Video ready")
    return project


def install() -> None:
    original_script_generate = services.ScriptService.generate

    def script_generate(self, project: Project, scene_count: int):
        return professional_script_generate(original_script_generate, self, project, scene_count)

    services.ScriptService.generate = script_generate
    pipeline.Pipeline.run = professional_run
