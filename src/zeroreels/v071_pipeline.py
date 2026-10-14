from __future__ import annotations

from pathlib import Path
import shutil
import time

from . import pipeline, services
from .config import PROJECTS_DIR
from .models import GenerationOptions, Project
from .v070_voice import voice_service_for
from .v070_visual import quality_retry_prompt_v2, visual_qa_v2
from .v071_runtime import rewrite_for_measured_duration_v2
from .v071_web_media import (
    WikimediaImageService,
    fetch_wikipedia_context,
    grounded_topic,
    hybrid_prefers_web,
)


def _planned_scene_count(project: Project, options: GenerationOptions) -> int:
    requested = max(3, int(options.scene_count))
    if not options.dynamic_visual_pacing:
        return requested
    dynamic = round(float(project.target_seconds) / 5.0)
    return max(requested, min(14, max(5, dynamic)))


def _preflight_for_options(self, options: GenerationOptions) -> None:
    rows = services.diagnostics(self.settings)
    required = {"Ollama", "Script model", "FFmpeg"}
    if options.image_source_mode != "Real Web Images":
        required.update({"ComfyUI", "FLUX.2 nodes", "FLUX.2 model", "FLUX.2 text encoder", "FLUX.2 VAE"})
    if options.voice_engine in {"Kokoro Directed", "Kokoro Classic"}:
        required.update({"Kokoro", "Voice model", "Voice pack"})
    failed = [label for label, ok, _ in rows if label in required and not ok]
    if failed:
        raise RuntimeError(
            "Generation is not ready yet. Open Setup and complete the missing items:\n• " + "\n• ".join(failed)
        )


def _quality_summary(project: Project) -> str:
    if not project.scenes:
        return "No scenes"
    retries = sum(scene.retry_count for scene in project.scenes)
    warnings = sum(1 for scene in project.scenes if scene.status == "image-warning")
    text_hits = sum(1 for scene in project.scenes if scene.ocr_text)
    real_count = sum(1 for scene in project.scenes if scene.source_type == "Wikimedia Commons")
    ai_count = len(project.scenes) - real_count
    passed = len(project.scenes) - warnings
    parts = [f"{passed}/{len(project.scenes)} visuals ready"]
    if real_count:
        parts.append(f"{real_count} real / {ai_count} AI")
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
        "Make the current composition unmistakably different from neighboring shots in subject scale, camera height, lens distance, viewing angle, location detail, or subject activity. "
        "Do not repeat the same group of people performing variations of one task. Prefer useful B-roll, environment, objects, consequences and authentic spatial context. "
        "For vertical video, keep important faces, hands and objects inside the middle 70% of frame and keep the lower 20% visually quiet for captions."
    )
    scene.director_note = density_note
    if density_note not in scene.image_prompt:
        marker = "[ZR-SEED="
        if marker in scene.image_prompt:
            pos = scene.image_prompt.rfind(marker)
            scene.image_prompt = scene.image_prompt[:pos].rstrip() + " " + density_note + " " + scene.image_prompt[pos:]
        else:
            scene.image_prompt += " " + density_note


def _write_sources(project: Project, out_dir: Path) -> None:
    rows = [scene for scene in project.scenes if scene.source_url]
    if not rows:
        return
    lines = [
        "ZeroReels real-media sources",
        "============================",
        "",
        "Licenses and attribution requirements remain the responsibility of the user. Verify the linked source page before publishing.",
        "",
    ]
    for scene in rows:
        lines.extend([
            f"Scene {scene.index:02d} — {scene.source_type}",
            f"Search: {scene.source_query}",
            f"Source: {scene.source_url}",
            f"Credit: {scene.source_credit or 'See source page'}",
            f"License: {scene.source_license or 'See source page'}",
            "",
        ])
    (out_dir / "SOURCES.txt").write_text("\n".join(lines), encoding="utf-8")


def reality_mix_run(self, project: Project, options: GenerationOptions, progress=lambda value, text: None) -> Project:
    progress(1, "Initializing Reality Mix pipeline")
    project.image_source_mode = options.image_source_mode
    if not options.mock_mode:
        progress(2, "Checking only the local engines this project needs")
        _preflight_for_options(self, options)
        progress(4, "Required local engines ready")

    stamp = time.strftime("%Y%m%d-%H%M%S")
    out_dir = PROJECTS_DIR / f"{stamp}-{pipeline.slugify(project.topic)}"
    out_dir.mkdir(parents=True, exist_ok=True)
    project.output_dir = str(out_dir)
    progress(5, "Project workspace ready")

    if options.research_grounding and not options.mock_mode:
        progress(6, "Research grounding • checking Wikipedia context")
        context, source = fetch_wikipedia_context(project.topic)
        project.research_context = context
        project.research_source = source
        if context:
            progress(7, "Research grounding ready • factual context attached")
        else:
            progress(7, "Research grounding unavailable • continuing with cautious local script")

    planned_count = _planned_scene_count(project, options)
    if planned_count != options.scene_count:
        progress(8, f"Dynamic pacing • {options.scene_count} requested scenes → {planned_count} visual beats")

    script_service = services.MockScriptService() if options.mock_mode else services.ScriptService(self.settings)
    try:
        script_service._zr_progress = progress
    except Exception:
        pass
    progress(9, "Writing natural retention-first narration")
    original_topic = project.topic
    if project.research_context and not options.mock_mode:
        project.topic = grounded_topic(original_topic, project.research_context)
    try:
        project.script, project.scenes = script_service.generate(project, planned_count)
    finally:
        project.topic = original_topic
    if not project.title or project.title == "Untitled Reel":
        project.title = project.topic.strip()[:100] or "Untitled Reel"
    for i in range(len(project.scenes)):
        _direct_visual_prompt(project, i)
    project.save(out_dir / "project.json")
    progress(15, "Story structure locked • directing voice performance")

    voice = voice_service_for(self.settings, options.voice_engine, options.voice_delivery, options.mock_mode)
    probe_dir = out_dir / "_runtime_probe"
    probe_dir.mkdir(parents=True, exist_ok=True)
    progress(16, f"Voice Director • {options.voice_engine} • {options.voice_delivery}")
    candidate_audio = voice.generate(project, probe_dir, progress=progress)
    measured = float(project.actual_seconds or sum(max(0.0, scene.duration) for scene in project.scenes))
    if options.mock_mode:
        measured = float(project.target_seconds)
        project.actual_seconds = measured

    if options.runtime_lock and not options.mock_mode:
        # Re-measure after every rewrite. v0.7 stopped after one rewrite even when the new
        # narration still missed badly (for example a 60s request landing around 40s).
        for pass_index in (1, 2):
            ratio = float(project.target_seconds) / max(0.001, measured)
            if 0.95 <= ratio <= 1.05:
                break
            changed = rewrite_for_measured_duration_v2(
                self.settings, project, measured, progress=progress, pass_index=pass_index
            )
            if not changed:
                break
            voice = voice_service_for(self.settings, options.voice_engine, options.voice_delivery, False)
            candidate_audio = voice.generate(project, probe_dir, progress=progress)
            measured = float(project.actual_seconds or sum(max(0.0, scene.duration) for scene in project.scenes))

    audio = out_dir / "narration.wav"
    shutil.copy2(candidate_audio, audio)
    project.actual_seconds = round(measured, 2)
    drift = abs(measured - float(project.target_seconds))
    if options.runtime_lock and not options.mock_mode and drift > max(3.0, project.target_seconds * 0.07):
        progress(33, f"Runtime Lock v2 warning • {measured:.1f}s actual / {project.target_seconds}s target")
    else:
        progress(33, f"Runtime Lock v2 ready • {measured:.1f}s actual / {project.target_seconds}s target")
    shutil.rmtree(probe_dir, ignore_errors=True)
    project.narration_path = str(audio)
    project.voice_engine_used = project.voice_engine_used or options.voice_engine
    project.voice_delivery = project.voice_delivery or options.voice_delivery
    project.save(out_dir / "project.json")

    progress(35, f"Narration locked • visual source: {options.image_source_mode}")
    ai_service = services.MockImageService() if options.mock_mode else services.ComfyImageService(self.settings)
    web_service = WikimediaImageService(project)
    count = len(project.scenes)
    image_start, image_end = 36, 71

    for i, scene in enumerate(project.scenes):
        start_pct = image_start + int((image_end - image_start) * i / max(1, count))
        end_pct = image_start + int((image_end - image_start) * (i + 1) / max(1, count))
        previous = project.scenes[i - 1] if i > 0 else None
        previous2 = project.scenes[i - 2] if i > 1 else None
        wants_web = (
            not options.mock_mode
            and options.image_source_mode in {"Real Web Images", "Hybrid"}
            and (options.image_source_mode == "Real Web Images" or hybrid_prefers_web(scene, i))
        )

        if wants_web:
            try:
                progress(start_pct, f"Scene {i + 1}/{count} • finding authentic Wikimedia image")
                image = web_service.generate(scene, out_dir, project.format)
                scene.image_path = str(image)
                scene.status = "image-ready"
                progress(max(start_pct + 1, end_pct - 1), f"Scene {i + 1}/{count} • real image ready • {scene.source_license}")
                project.save(out_dir / "project.json")
                continue
            except Exception as exc:
                if options.image_source_mode == "Real Web Images":
                    raise RuntimeError(
                        f"Real Web Images could not find/download a usable scene {i + 1} image. "
                        "Try a broader topic or switch Image Source to Hybrid.\n" + str(exc)
                    ) from exc
                progress(start_pct, f"Scene {i + 1}/{count} • web image unavailable • using AI fallback ({str(exc)[:90]})")

        scene.source_type = "AI Generated"
        scene.source_url = ""
        scene.source_credit = ""
        scene.source_license = ""
        retries = 0 if options.mock_mode or not options.quality_guard else max(0, int(options.quality_retries))
        accepted = False
        last_image: Path | None = None
        for attempt in range(retries + 1):
            if attempt:
                scene.image_prompt = quality_retry_prompt_v2(scene, attempt)
                progress(start_pct, f"Scene {i + 1}/{count} • Visual QA retry {attempt}/{retries}")
            else:
                progress(start_pct, f"Scene {i + 1}/{count} • AI {scene.shot_role or 'directed shot'}")
            last_image = ai_service.generate(scene, out_dir, project.format)
            scene.image_path = str(last_image)
            if options.mock_mode or not options.visual_qa_v2:
                scene.quality_score = 100
                scene.quality_notes = ["Visual QA v2 skipped"]
                accepted = True
            else:
                score, notes, accepted = visual_qa_v2(
                    last_image, scene, self.settings, previous=previous, previous2=previous2,
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

    _write_sources(project, out_dir)
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
        project, audio, captions, out_dir, motion=options.motion, transitions=options.transitions,
        caption_position=options.caption_position, caption_size=options.caption_size,
        transition_style=options.transition_style,
    )
    project.video_path = str(video)
    project.captions_burned = burned
    project.save(out_dir / "project.json")
    progress(99, f"Reality Mix final • {project.actual_seconds:.1f}s • {project.voice_engine_used}")
    progress(100, "Video ready")
    return project


def install() -> None:
    pipeline.Pipeline.run = reality_mix_run
