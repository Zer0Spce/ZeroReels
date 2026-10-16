from __future__ import annotations

from dataclasses import replace
from pathlib import Path
import re

from . import pipeline, services, ui, v060_story, v071_pipeline, v080_script, v090_editor


_INSTALLED = False
_FORCE_VIDEO_ONLY = False
_PREVIOUS_SCRIPT_GENERATE = None
_PREVIOUS_PIPELINE_RUN = None
_PREVIOUS_CREATE_PAGE = None
_PREVIOUS_SIDEBAR = None
_ORIGINAL_HYBRID_PREFERS_WEB = None
_ORIGINAL_VIDEO_QUERIES = None


def _clean(text: str) -> str:
    return " ".join((text or "").split()).strip()


def _number_tokens(text: str) -> set[str]:
    return set(re.findall(r"\b\d[\d,.:/%-]*\b", text or ""))


def _query_from_scene(project, scene) -> str:
    """Deterministic fallback when the writer cannot produce a media query."""
    subject = v090_editor.v071_web_media.primary_subject(project)
    words = v090_editor.v071_web_media._keywords(scene.narration, 5)
    prompt_words = v090_editor.v071_web_media._keywords(scene.image_prompt, 3)
    parts: list[str] = []
    if subject:
        parts.append(subject)
    for word in [*words, *prompt_words]:
        if word.casefold() not in {x.casefold() for x in parts}:
            parts.append(word)
        if len(parts) >= 6:
            break
    return _clean(" ".join(parts)) or _clean(project.topic)[:80]


def _editorial_pass(service, project, scenes, model: str) -> tuple[list[str], list[str]]:
    count = len(scenes)
    schema = {
        "type": "object",
        "properties": {
            "scenes": {
                "type": "array",
                "minItems": count,
                "maxItems": count,
                "items": {
                    "type": "object",
                    "properties": {
                        "narration": {"type": "string"},
                        "broll_query": {"type": "string"},
                        "media_preference": {"type": "string"},
                    },
                    "required": ["narration", "broll_query", "media_preference"],
                },
            }
        },
        "required": ["scenes"],
    }
    script_block = "\n".join(f"{i + 1}. {scene.narration}" for i, scene in enumerate(scenes))
    prompt = f"""You are the final story editor AND footage researcher for a high-retention short-form video.

TOPIC / RESEARCH CONTEXT:
{project.topic}

TARGET RUNTIME: {project.target_seconds} seconds
SCENES: exactly {count}

The draft below is already fact-checked as far as the available context allows. Improve only the delivery and editing usefulness.

RETENTION EDIT
- Preserve every factual claim, name, number, date, relationship and stance. Do not add facts.
- The first sentence must earn attention immediately with a concrete consequence, conflict, reversal, mystery, or unusually specific detail.
- No generic creator hooks, greetings, title-reading, rhetorical filler, or "wait until the end" language.
- By scene 2 the viewer should understand why the story matters.
- Every scene must advance the story. Remove paraphrased beats and repeated conclusions.
- Put the strongest turn or payoff around the final third when the material supports it.
- Write for speech: contractions, natural syntax, mixed sentence lengths, plain verbs, concrete nouns.
- Avoid robotic contrast templates, overuse of fragments, dramatic adjective stacking, and essay transitions.
- The final line should land the idea; no recap and no CTA unless the draft already has one.

FOOTAGE RESEARCH
For every scene write one broll_query of 2-7 words that a real footage search engine could use.
- Prefer named people, places, events, machines, actions, objects, or environments visible on screen.
- Use literal searchable words, not abstract phrases like "dramatic turning point" or "cinematic footage".
- When movement matters, media_preference should be "video". Use "image" for static archival material, or "either" when both work.
- Do not repeat the same query across scenes unless the spoken beat truly requires it.

DRAFT:
{script_block}

Return only the required JSON."""
    data = v080_script._json_call(service, model, prompt, schema, temperature=0.38)
    rows = data.get("scenes", [])
    if len(rows) != count:
        raise RuntimeError("Story Director v3 returned an incomplete editorial plan")
    narrations = [_clean(str(row.get("narration", ""))) for row in rows]
    queries = [_clean(str(row.get("broll_query", ""))) for row in rows]
    if not all(narrations):
        raise RuntimeError("Story Director v3 returned empty narration")
    return narrations, queries


def _rewrite_is_safe(original: list[str], candidate: list[str], target_words: int) -> bool:
    original_text = " ".join(original)
    candidate_text = " ".join(candidate)
    if not candidate or not v080_script._hook_ok(candidate[0]):
        return False
    if _number_tokens(candidate_text) - _number_tokens(original_text):
        return False
    words = v080_script._word_count(candidate_text)
    if words < int(target_words * 0.86) or words > int(target_words * 1.14):
        return False
    before = v080_script._script_problems(original, target_words)
    after = v080_script._script_problems(candidate, target_words)
    return len(after) <= len(before)


def _ensure_shot_roles(project, scenes) -> None:
    if scenes and not any((scene.shot_role or "").strip() for scene in scenes):
        v060_story._apply_professional_visual_direction(project, scenes)


def story_director_v3(self, project, scene_count: int):
    script, scenes = _PREVIOUS_SCRIPT_GENERATE(self, project, scene_count)
    if not scenes:
        return script, scenes
    _ensure_shot_roles(project, scenes)

    mode = getattr(project, "script_mode", "AI Script") or "AI Script"
    wants_media_plan = bool(getattr(project, "web_video_broll", False))
    if mode == "Custom Script" and not wants_media_plan:
        return script, scenes

    model = getattr(project, "script_model_used", "") or v080_script.resolve_writer_model(
        self.settings, getattr(project, "script_model_mode", "Auto Quality")
    )[0]
    v080_script._progress(self, 13, "Story Director v3 • retention edit + footage search plan")

    original = [scene.narration for scene in scenes]
    target_words = max(55, round(project.target_seconds * 2.45))
    try:
        candidate, queries = _editorial_pass(self, project, scenes, model)
    except Exception as exc:
        queries = [_query_from_scene(project, scene) for scene in scenes]
        project.script_quality_summary = _clean(
            (getattr(project, "script_quality_summary", "") + f" • v3 footage planner fallback: {str(exc)[:80]}")
        )
        for scene, query in zip(scenes, queries):
            scene.source_query = "Planned B-roll: " + query
        return script, scenes

    allow_rewrite = mode in {"AI Script", "AI Polish My Script"}
    if allow_rewrite and _rewrite_is_safe(original, candidate, target_words):
        narrations = candidate
        # Re-direct the visuals after the final retention edit so spoken words and shots stay aligned.
        try:
            title, anchor, continuity, prompts = v080_script._visual_plan(self, project, model, narrations)
            scenes = v080_script._build_scenes(project, narrations, prompts, anchor, continuity)
            project.title = title or project.title
            script = " ".join(narrations).strip()
            project.script = script
        except Exception:
            # Keep the proven v2 visuals if the extra directing pass fails.
            narrations = original
            script = " ".join(original).strip()
    else:
        narrations = original

    if len(queries) != len(scenes):
        queries = [_query_from_scene(project, scene) for scene in scenes]
    for scene, query in zip(scenes, queries):
        query = query or _query_from_scene(project, scene)
        scene.source_query = "Planned B-roll: " + query[:120]

    # Rebuilding the scenes above creates fresh objects, so restore editing roles again.
    _ensure_shot_roles(project, scenes)

    wc = v080_script._word_count(" ".join(scene.narration for scene in scenes))
    project.script_quality_summary = _clean(
        (getattr(project, "script_quality_summary", "") + f" • Story Director v3 • {wc} words • editor-aware B-roll plan")
    )
    v080_script._progress(self, 14, "Story Director v3 ready • narration and footage searches aligned")
    return script, scenes


def smart_video_queries(project, scene) -> list[str]:
    planned = _clean(getattr(scene, "source_query", ""))
    if planned.lower().startswith("planned b-roll:"):
        planned = _clean(planned.split(":", 1)[1])
    else:
        planned = ""
    base = _ORIGINAL_VIDEO_QUERIES(project, scene)
    candidates = ([planned] if planned else []) + list(base)
    unique: list[str] = []
    seen: set[str] = set()
    for value in candidates:
        value = _clean(value)
        key = value.casefold()
        if value and key not in seen:
            seen.add(key)
            unique.append(value)
    return unique


def _motion_slot(scene, index: int) -> bool:
    role = (getattr(scene, "shot_role", "") or "").casefold()
    if role in {"action", "escalation", "peak"}:
        return True
    return role in {"establishing", "aftermath"} and index % 3 == 0


def smart_hybrid_prefers_web(scene, index: int) -> bool:
    if _FORCE_VIDEO_ONLY:
        return _motion_slot(scene, index)
    return _ORIGINAL_HYBRID_PREFERS_WEB(scene, index)


class VideoFirstMediaService(v090_editor.WikimediaMediaService):
    """In AI-image mode, use the web only when a real video match exists; otherwise fall back to AI."""

    def generate(self, scene, out_dir: Path, fmt: str) -> Path:
        if _FORCE_VIDEO_ONLY:
            if not self._wants_motion(scene):
                raise RuntimeError("Scene is not scheduled for online motion B-roll")
            result = v090_editor._download_video(self.project, scene, out_dir)
            self.video_count += 1
            return result
        return super().generate(scene, out_dir, fmt)


def video_any_source_pipeline(self, project, options, progress=lambda value, text: None):
    global _FORCE_VIDEO_ONLY
    force = (
        bool(getattr(options, "web_video_broll", True))
        and not bool(getattr(options, "mock_mode", False))
        and getattr(options, "image_source_mode", "AI Generated") == "AI Generated"
    )
    if not force:
        return _PREVIOUS_PIPELINE_RUN(self, project, options, progress)

    original_mode = options.image_source_mode
    hybrid_options = replace(options, image_source_mode="Hybrid")
    _FORCE_VIDEO_ONLY = True
    try:
        progress(34, "Online B-roll • AI visuals stay primary; searching licensed motion clips for key beats")
        result = _PREVIOUS_PIPELINE_RUN(self, project, hybrid_options, progress)
        result.image_source_mode = original_mode
        if result.output_dir:
            result.save(Path(result.output_dir) / "project.json")
        return result
    finally:
        _FORCE_VIDEO_ONLY = False


def sidebar_v100(self):
    frame = _PREVIOUS_SIDEBAR(self)
    try:
        from PySide6.QtWidgets import QLabel
        for label in frame.findChildren(QLabel):
            if label.text().startswith("v0."):
                label.setText("v0.10 STORY + VIDEO")
                label.setMaximumWidth(164)
                break
    except Exception:
        pass
    return frame


def create_page_v100(self):
    page = _PREVIOUS_CREATE_PAGE(self)
    check = getattr(self, "web_video_broll_check", None)
    if check is not None:
        check.setText("Online motion B-roll (auto)")
        check.setEnabled(True)
        check.setToolTip(
            "Searches license-traceable Wikimedia Commons video for key spoken beats and stitches matching clips into the reel. "
            "Works with AI Generated, Hybrid, and Real Web Images. Weak matches fall back to your normal visual source."
        )
        box = getattr(self, "image_source_box", None)
        if box is not None:
            box.currentTextChanged.connect(lambda _value, c=check: c.setEnabled(True))
    return page


def install() -> None:
    global _INSTALLED
    global _PREVIOUS_SCRIPT_GENERATE, _PREVIOUS_PIPELINE_RUN, _PREVIOUS_CREATE_PAGE, _PREVIOUS_SIDEBAR
    global _ORIGINAL_HYBRID_PREFERS_WEB, _ORIGINAL_VIDEO_QUERIES
    if _INSTALLED:
        return

    _PREVIOUS_SCRIPT_GENERATE = services.ScriptService.generate
    _PREVIOUS_PIPELINE_RUN = pipeline.Pipeline.run
    _PREVIOUS_CREATE_PAGE = ui.MainWindow._create_page
    _PREVIOUS_SIDEBAR = ui.MainWindow._sidebar
    _ORIGINAL_HYBRID_PREFERS_WEB = v071_pipeline.hybrid_prefers_web
    _ORIGINAL_VIDEO_QUERIES = v090_editor._video_queries

    services.ScriptService.generate = story_director_v3
    v090_editor._video_queries = smart_video_queries
    v071_pipeline.hybrid_prefers_web = smart_hybrid_prefers_web
    v071_pipeline.WikimediaImageService = VideoFirstMediaService
    pipeline.Pipeline.run = video_any_source_pipeline
    ui.MainWindow._create_page = create_page_v100
    ui.MainWindow._sidebar = sidebar_v100
    _INSTALLED = True
