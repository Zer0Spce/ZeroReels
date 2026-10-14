from __future__ import annotations

from pathlib import Path
import shutil
import time

from . import pipeline, services
from .config import PROJECTS_DIR
from .models import GenerationOptions, Project
from .v070_voice import rewrite_for_measured_duration, voice_service_for
from .v070_visual import quality_retry_prompt_v2, visual_qa_v2


def _planned_scene_count(project: Project, options: GenerationOptions) -> int:
    requested = max(3, int(options.scene_count))
    if not options.dynamic_visual_pacing:
        return requested
    # Human-edited short-form video tends to feel better around one meaningful visual beat
    # every 4.5–5.5 seconds. Respect a larger manual request, but automatically raise sparse
    # 45–90 second reels to a denser visual rhythm.
    dynamic = round(float(project.target_seconds) / 5.0)
    return max(requested, min(14, max(5, dynamic)))


def _quality_summary(project: Project) -> str:
    if not project.scenes:
        return "No scenes"
    retries = sum(scene.retry_count for scene in project.scenes)
    warnings = sum(1 for scene in project.scenes if scene.status == "image-warning")
    text_hits = sum(1 for scene in project.scenes if scene.ocr_text)
    passed = len(project.scenes) - warnings
    parts = [f"{passed}/{len(project.scenes)} visuals passed QA v2"]
    if retries:
        parts.append(f"{retries} regeneration(s)")
    if text_hits:
        parts.append(f"{text_hits} readable-text warning(s)")
    return " • ".join(parts)


def _direct_visual_prompt(project: Project, index: int) -> None:
    scene = project.scenes[index]
    previous_role = project.scenes[index - 1].shot_role if index > 0 else "none"
    next_role = project.scenes[index + 1].shot_role if index + 1 < len(project.scenes) else "none"
    density_note = (
        f"Human editor continuity: this is visual beat {index + 1}/{len(project.scenes)}. "
        f"Previous shot role: {previous_role}; current role: {scene.shot_role or 'Action'}; next role: {next_role}. "
        "Make the current composition unmistakably different from the neighboring shots in subject scale, camera height, lens distance, or viewing angle. "
        "Prefer candid action and useful B-roll over a centered person posing. For vertical video, keep important faces, hands and objects inside the middle 70% of frame and keep the lower 20% visually quiet for captions."
    )
    scene.director_note = density_note
    if density_note not in scene.image_prompt:
        marker = "[ZR-SEED="
        if marker in scene.image_prompt:
            pos = scene.image_prompt.rfind(marker)
            scene.image_prompt = scene.image_prompt[:pos].rstrip() + " " + density_note + " " + scene.image_prompt[pos:]
        else:
            scene.image_prompt += " " + density_note


def human_touch_run(self, project: Project, options: GenerationOptions, progress=lambda value, text: None) -> Project:
    progress(1, "Initializing Human Touch pipeline")
    if not options.mock_mode:
        progress(2, "Checking local AI setup")
        self._preflight()
        progress(4, "Local AI setup ready")

    stamp = time.strftime("%Y%m%d-%H%M%S")
    out_dir = PROJECTS_DIR / f"{stamp}-{pipeline.slugify(project.topic)}"
    out_dir.mkdir(parents=True, exist_ok=True)
    project.output_dir = str(out_dir)
    progress(5, "Project workspace ready")

    planned_count = _planned_scene_count(project, options)
    if planned_count != options.scene_count:
        progress(6, f"Dynamic pacing • {options.scene_count} requested scenes → {planned_count} visual beats")
    script_service = services.MockScriptService() if options.mock_mode else services.ScriptService(self.settings)
    try:
        script_service._zr_progress = progress
    except Exception:
        pass
    progress(7, "Writing natural retention-first narration")
    project.script, project.scenes = script_service.generate(project, planned_count)
    if not project.title or project.title == "Untitled Reel":
        project.title = project.topic.strip()[:100] or "Untitled Reel"
    for i in range(len(project.scenes)):
        _direct_visual_prompt(project, i)
    project.save(out_dir / "project.json")
    progress(14, "Story structure locked • directing voice performance")

    # Voice comes before expensive image generation in v0.7. This lets ZeroReels measure
    # real speech duration and fix a 46s '60 second' reel before spending time on FLUX.
    voice = voice_service_for(self.settings, options.voice_engine, options.voice_delivery, options.mock_mode)
    probe_dir = out_dir / "_runtime_probe"
    probe_dir.mkdir(parents=True, exist_ok=True)
    progress(15, f"Voice Director • {options.voice_engine} • {options.voice_delivery}")
    probe_audio = voice.generate(project, probe_dir, progress=progress)
    measured = float(project.actual_seconds or sum(max(0.0, scene.duration) for scene in project.scenes))
    if options.mock_mode:
        measured = float(project.target_seconds)
        project.actual_seconds = measured

    rewritten = False
    if options.runtime_lock and not options.mock_mode:
        rewritten = rewrite_for_measured_duration(self.settings, project, measured, progress)
    if rewritten:
        progress(33, "Re-performing final narration after measured runtime edit")
        voice = voice_service_for(self.settings, options.voice_engine, options.voice_delivery, False)
        audio = voice.generate(project, out_dir, progress=progress)
    else:
        audio = out_dir / "narration.wav"
        shutil.copy2(probe_audio, audio)
        progress(33, f"Runtime locked • {project.actual_seconds:.1f}s actual / {project.target_seconds}s target")
    try:
        shutil.rmtree(probe_dir, ignore_errors=True)
    except Exception:
        pass
    project.narration_path = str(audio)
    project.actual_seconds = round(sum(max(0.0, scene.duration) for scene in project.scenes), 2)
    project.voice_engine_used = project.voice_engine_used or options.voice_engine
    project.voice_delivery = project.voice_delivery or options.voice_delivery
    project.save(out_dir / "project.json")

    progress(35, "Narration locked • generating human-directed visuals")
    image_service = services.MockImageService() if options.mock_mode else services.ComfyImageService(self.settings)
    count = len(project.scenes)
    image_start, image_end = 36, 71
    for i, scene in enumerate(project.scenes):
        start_pct = image_start + int((image_end - image_start) * i / max(1, count))
        end_pct = image_start + int((image_end - image_start) * (i + 1) / max(1, count))
        previous = project.scenes[i - 1] if i > 0 else None
        previous2 = project.scenes[i - 2] if i > 1 else None
        retries = 0 if options.mock_mode or not options.quality_guard else max(0, int(options.quality_retries))
        accepted = False
        last_image: Path | None = None

        for attempt in range(retries + 1):
            if attempt:
                scene.image_prompt = quality_retry_prompt_v2(scene, attempt)
                progress(start_pct, f"Scene {i + 1}/{count} • Visual QA retry {attempt}/{retries}")
            else:
                progress(start_pct, f"Scene {i + 1}/{count} • {scene.shot_role or 'Directed shot'}")
            last_image = image_service.generate(scene, out_dir, project.format)
            scene.image_path = str(last_image)
            if options.mock_mode or not options.visual_qa_v2:
                scene.quality_score = 100
                scene.quality_notes = ["Visual QA v2 skipped"]
                accepted = True
            else:
                score, notes, accepted = visual_qa_v2(
                    last_image,
                    scene,
                    self.settings,
                    previous=previous,
                    previous2=previous2,
                    ocr_guard=bool(options.ocr_guard),
                )
                scene.quality_score = score
                scene.quality_notes = notes
                if not accepted and attempt < retries:
                    reason = notes[0] if notes else "weak visual"
                    progress(start_pct, f"Scene {i + 1} QA {score}/100 • {reason} • regenerating")
            scene.retry_count = attempt
            if accepted:
                break

        if last_image is None:
            raise RuntimeError(f"Scene {i + 1} did not produce an image")
        if accepted:
            scene.status = "image-ready"
            progress(max(start_pct + 1, end_pct - 1), f"Scene {i + 1}/{count} accepted • QA {scene.quality_score}/100")
        else:
            scene.status = "image-warning"
            reason = scene.quality_notes[0] if scene.quality_notes else "quality warning"
            progress(max(start_pct + 1, end_pct - 1), f"Scene {i + 1}/{count} kept after retries • {reason}")
        project.save(out_dir / "project.json")

    project.quality_summary = _quality_summary(project)
    project.visual_qa_summary = project.quality_summary
    progress(72, project.quality_summary)

    captions = None
    if options.captions:
        progress(74, f"Building speech-paced {options.caption_style} captions")
        caption_service = services.CaptionService()
        caption_service._zr_caption_style = options.caption_style
        caption_service._zr_caption_position = options.caption_position
        caption_service._zr_caption_size = options.caption_size
        captions = caption_service.generate_from_scenes(project, out_dir)
        project.captions_path = str(captions)
        progress(78, "Captions timed to final narration")
    else:
        progress(78, "Captions disabled")

    progress(80, "Human editor pass • motion, cuts, grade and sound design")
    renderer = services.FFmpegRenderer(self.settings)
    renderer._zr_progress = progress
    renderer._zr_caption_style = options.caption_style
    renderer._zr_caption_filename = Path(captions).name if captions else ""
    renderer._zr_soundtrack_mode = options.soundtrack_mode if options.music else "Off"
    renderer._zr_sfx = bool(options.sfx)
    renderer._zr_project = project
    renderer._zr_dynamic_visual_pacing = bool(options.dynamic_visual_pacing)

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
    progress(99, f"Human Touch final • {project.actual_seconds:.1f}s • {project.voice_engine_used}")
    progress(100, "Video ready")
    return project


def install() -> None:
    pipeline.Pipeline.run = human_touch_run
