from __future__ import annotations

import json
import re
import urllib.request
from collections import Counter

from . import services
from .models import Project, Scene
from .v053_quality import _build_scene_prompt, _style_profile, _too_repetitive

QUALITY_MODEL = "qwen3:8b"

_BANNED_CLICHES = (
    "did you know",
    "imagine this",
    "picture this",
    "but here's the crazy part",
    "but here is the crazy part",
    "you won't believe",
    "this changes everything",
    "let that sink in",
    "have you ever wondered",
    "in a world where",
    "this is the story of",
    "little did they know",
    "what happened next",
    "the answer may surprise you",
    "it is important to note",
    "in conclusion",
)


def _progress(service, value: int, text: str) -> None:
    callback = getattr(service, "_zr_progress", None)
    if callback:
        callback(value, text)


def _word_count(text: str) -> int:
    return len(re.findall(r"\b[\w'’-]+\b", text or ""))


def _sentence_count(text: str) -> int:
    return len([x for x in re.split(r"(?<=[.!?])\s+", (text or "").strip()) if x.strip()])


def _available_models(settings) -> set[str]:
    try:
        url = settings.ollama_url.rstrip("/") + "/api/tags"
        with urllib.request.urlopen(url, timeout=4) as response:
            data = json.loads(response.read().decode("utf-8", errors="replace"))
        found = set()
        for item in data.get("models", []):
            value = str(item.get("name") or item.get("model") or "").strip()
            if value:
                found.add(value)
        return found
    except Exception:
        return set()


def _model_present(models: set[str], wanted: str) -> bool:
    base = wanted.split(":", 1)[0]
    return wanted in models or any(name == wanted or name.startswith(wanted + "-") for name in models) or any(
        name.startswith(base + ":") and wanted.endswith(name.split(":", 1)[1]) for name in models if ":" in name
    )


def resolve_writer_model(settings, mode: str) -> tuple[str, str]:
    mode = (mode or "Auto Quality").strip()
    current = settings.ollama_model or "qwen3:4b"
    if "4B" in mode or mode == "Fast":
        return current, "Fast"
    models = _available_models(settings)
    if _model_present(models, QUALITY_MODEL):
        return QUALITY_MODEL, "Quality"
    if "8B" in mode:
        return current, "Quality model unavailable — fallback"
    return current, "Auto fallback"


def _json_call(service, model: str, prompt: str, schema: dict, *, temperature: float = 0.45, timeout: int = 600) -> dict:
    endpoint = service.settings.ollama_url.rstrip("/") + "/api/generate"
    result = services._post_json(
        endpoint,
        {
            "model": model,
            "prompt": prompt,
            "stream": False,
            "format": schema,
            "think": False,
            "options": {
                "temperature": temperature,
                "top_p": 0.9,
                "repeat_penalty": 1.12,
                "num_ctx": 8192,
            },
        },
        timeout=timeout,
    )
    try:
        return json.loads(result["response"])
    except Exception as exc:
        raise RuntimeError("Ollama returned invalid structured output") from exc


def _script_text(scenes: list[Scene] | list[str]) -> str:
    if scenes and isinstance(scenes[0], Scene):
        return " ".join(scene.narration for scene in scenes).strip()
    return " ".join(str(x) for x in scenes).strip()


def _hook_ok(text: str) -> bool:
    first = re.split(r"(?<=[.!?])\s+", (text or "").strip(), maxsplit=1)[0].strip()
    if not first:
        return False
    lower = first.lower()
    if any(lower.startswith(value) or value in lower for value in _BANNED_CLICHES):
        return False
    words = _word_count(first)
    return 5 <= words <= 22


def _script_problems(texts: list[str], target_words: int) -> list[str]:
    combined = " ".join(texts).strip()
    lower = combined.lower()
    problems: list[str] = []
    wc = _word_count(combined)
    if wc < int(target_words * 0.90):
        problems.append(f"too short ({wc}/{target_words} words)")
    elif wc > int(target_words * 1.12):
        problems.append(f"too long ({wc}/{target_words} words)")
    if not texts or not _hook_ok(texts[0]):
        problems.append("opening hook is weak or generic")
    clichés = [phrase for phrase in _BANNED_CLICHES if phrase in lower]
    if clichés:
        problems.append("canned phrasing: " + ", ".join(clichés[:3]))
    starts = []
    for text in texts:
        words = re.findall(r"[a-z']+", text.lower())
        if words:
            starts.append(" ".join(words[:2]))
    if any(count >= 3 for count in Counter(starts).values()):
        problems.append("repetitive sentence openings")
    scenes = [Scene(index=i + 1, narration=t, image_prompt="") for i, t in enumerate(texts)]
    if len(scenes) > 1 and _too_repetitive(scenes):
        problems.append("repeated or paraphrased beats")
    return problems


def _atomic_segments(text: str) -> list[str]:
    cleaned = " ".join((text or "").replace("\r", " ").replace("\n", " ").split()).strip()
    if not cleaned:
        return []
    parts = re.split(
        r"(?<=[.!?;:])\s+|(?<=,)\s+(?=(?:but|and|so|while|because|then|yet|although|when)\b)",
        cleaned,
        flags=re.IGNORECASE,
    )
    return [part.strip() for part in parts if part.strip()]


def split_custom_script(text: str, scene_count: int) -> list[str]:
    """Split user narration into visual beats without rewriting or reordering its words."""
    scene_count = max(1, int(scene_count))
    atoms = _atomic_segments(text)
    if not atoms:
        return []

    # If the script has too few natural clauses, split the longest clauses at word boundaries.
    while len(atoms) < scene_count:
        idx = max(range(len(atoms)), key=lambda i: _word_count(atoms[i]))
        words = atoms[idx].split()
        if len(words) < 6:
            break
        midpoint = max(3, len(words) // 2)
        atoms[idx:idx + 1] = [" ".join(words[:midpoint]), " ".join(words[midpoint:])]

    total_words = sum(_word_count(atom) for atom in atoms)
    target = max(1.0, total_words / scene_count)
    groups: list[list[str]] = [[]]
    running = 0
    remaining_groups = scene_count

    for pos, atom in enumerate(atoms):
        atom_words = _word_count(atom)
        atoms_left = len(atoms) - pos
        should_break = (
            groups[-1]
            and len(groups) < scene_count
            and running + atom_words > target * 1.18
            and atoms_left >= (scene_count - len(groups))
        )
        if should_break:
            groups.append([])
            running = 0
            remaining_groups -= 1
        groups[-1].append(atom)
        running += atom_words

    while len(groups) < scene_count:
        idx = max(range(len(groups)), key=lambda i: _word_count(" ".join(groups[i])))
        words = " ".join(groups[idx]).split()
        if len(words) < 6:
            break
        midpoint = max(3, len(words) // 2)
        groups[idx:idx + 1] = [[" ".join(words[:midpoint])], [" ".join(words[midpoint:])]]

    # More beats than requested: merge the smallest adjacent pair until exact.
    while len(groups) > scene_count:
        pair = min(
            range(len(groups) - 1),
            key=lambda i: _word_count(" ".join(groups[i])) + _word_count(" ".join(groups[i + 1])),
        )
        groups[pair:pair + 2] = [groups[pair] + groups[pair + 1]]

    return [" ".join(group).strip() for group in groups if group]


def _visual_plan(service, project: Project, model: str, narrations: list[str]) -> tuple[str, str, str, list[str]]:
    count = len(narrations)
    schema = {
        "type": "object",
        "properties": {
            "title": {"type": "string"},
            "visual_anchor": {"type": "string"},
            "continuity_bible": {"type": "string"},
            "scenes": {
                "type": "array",
                "minItems": count,
                "maxItems": count,
                "items": {
                    "type": "object",
                    "properties": {"image_prompt": {"type": "string"}},
                    "required": ["image_prompt"],
                },
            },
        },
        "required": ["title", "visual_anchor", "continuity_bible", "scenes"],
    }
    narration_block = "\n".join(f"{i + 1}. {text}" for i, text in enumerate(narrations))
    prompt = f"""You are the visual director for a premium short-form vertical video.
TOPIC: {project.topic}
STYLE: {project.style}
CONTINUITY: {project.continuity_mode}

The narration is FINAL. Do not rewrite it. Design one specific visual beat for each narration segment.

VISUAL DIRECTION
- Every shot must directly support the words currently being spoken.
- Change shot scale, camera angle, activity, location detail, or subject emphasis from one beat to the next.
- Use useful B-roll and environments; do not make every shot a centered portrait.
- For biography/history, mix faces with locations, objects, crowds, action, aftermath, architecture and contextual details.
- Avoid poster compositions, collages, split screens, inset frames, duplicated people and staged "holding a document at camera" shots.
- Do not request readable text, screens, labels, newspapers, badges, logos, maps with legible writing, UI or subtitles.
- Keep recurring people/places coherent when they naturally recur.
- In vertical framing, protect the center subject and keep key anatomy away from extreme edges.

FINAL NARRATION:
{narration_block}

Return only the required JSON."""
    data = _json_call(service, model, prompt, schema, temperature=0.42)
    prompts = [" ".join(str(item.get("image_prompt", "")).split()).strip() for item in data.get("scenes", [])]
    if len(prompts) != count or not all(prompts):
        raise RuntimeError("Story Director returned an incomplete visual plan")
    title = " ".join(str(data.get("title") or project.topic).split()).strip()[:100]
    anchor = " ".join(str(data.get("visual_anchor") or f"{project.style}, cohesive cinematic production design").split()).strip()
    continuity = " ".join(str(data.get("continuity_bible") or "keep recurring subjects and locations visually stable when they recur").split()).strip()
    return title, anchor, continuity, prompts


def _build_scenes(project: Project, narrations: list[str], prompts: list[str], anchor: str, continuity: str) -> list[Scene]:
    import hashlib
    material = f"{project.topic}|{project.style}|{anchor}|{continuity}".encode("utf-8")
    base_seed = int(hashlib.sha256(material).hexdigest()[:8], 16) % 2_147_483_647
    provisional = max(1.2, project.target_seconds / max(1, len(narrations)))
    scenes = []
    for i, (narration, visual) in enumerate(zip(narrations, prompts)):
        scenes.append(
            Scene(
                index=i + 1,
                narration=narration.strip(),
                image_prompt=_build_scene_prompt(project, anchor, continuity, visual, i, base_seed),
                duration=provisional,
                reuse_previous_image=False,
            )
        )
    return scenes


def _polish_user_script(service, project: Project, model: str, text: str, target_words: int) -> str:
    schema = {
        "type": "object",
        "properties": {"script": {"type": "string"}},
        "required": ["script"],
    }
    prompt = f"""You are a human short-form narration editor. Rewrite the user's draft so it sounds like a naturally spoken TikTok/Reels story.

TOPIC: {project.topic}
STYLE: {_style_profile(project.style)}
TARGET: roughly {target_words} spoken words, but preserve useful content over padding.

NON-NEGOTIABLES
- Preserve the user's facts, names, dates, claims, stance and intended meaning. Do not invent any fact.
- Build a real hook in the first sentence: conflict, consequence, contrast, mystery or an unusually specific detail.
- The hook must sound like a person speaking. Avoid "Did you know", "Imagine this", "Picture this", "You won't believe", "This is the story of", "But here's the crazy part" and similar creator clichés.
- Write for the ear, not the page. Use contractions, natural sentence lengths and plain transitions.
- Vary rhythm: some short lines, some medium lines. Do not make every sentence a dramatic fragment.
- Cut repetition, filler, throat-clearing and summary language.
- Avoid school-essay connectors like therefore, furthermore, consequently and in conclusion.
- Avoid repeated templates such as "It wasn't just X. It was Y" or "Not only X, but Y".
- Escalate naturally and finish on a line that lands the idea rather than summarizing it.
- No CTA unless the user's draft already contains one.

USER DRAFT:
{text}

Return only JSON."""
    data = _json_call(service, model, prompt, schema, temperature=0.48)
    value = " ".join(str(data.get("script", "")).split()).strip()
    return value or text


def story_director_generate(self, project: Project, scene_count: int):
    mode = getattr(project, "script_mode", "AI Script") or "AI Script"
    model_mode = getattr(project, "script_model_mode", "Auto Quality") or "Auto Quality"
    model, resolution = resolve_writer_model(self.settings, model_mode)
    project.script_model_used = model
    _progress(self, 7, f"Story Director v2 • {mode} • writer {model}")
    if "fallback" in resolution.lower():
        _progress(self, 7, f"Quality writer not installed • using {model}")

    target_words = max(55, round(project.target_seconds * 2.45))

    if mode in {"Custom Script", "AI Polish My Script"}:
        source = (getattr(project, "custom_script", "") or "").strip()
        if not source:
            raise RuntimeError("Paste a script in Create before using Custom Script mode.")
        if mode == "AI Polish My Script":
            _progress(self, 8, "Polishing your script • keeping facts and intent intact")
            source = _polish_user_script(self, project, model, source, target_words)
            project.script_quality_summary = "User script polished by Story Director v2"
        else:
            project.script_quality_summary = "User script preserved verbatim except beat whitespace"
        narrations = split_custom_script(source, scene_count)
        if not narrations:
            raise RuntimeError("The pasted script is empty or could not be split into narration beats.")
        project.script = " ".join(narrations)
        _progress(self, 10, f"Custom narration locked • {_word_count(project.script)} words • planning visuals")
        title, anchor, continuity, prompts = _visual_plan(self, project, model, narrations)
        project.title = title or project.topic[:100]
        scenes = _build_scenes(project, narrations, prompts, anchor, continuity)
        _progress(self, 13, "Custom script mapped to visual beats")
        return project.script, scenes

    # AI Script: deliberately separate story thinking from prose writing. Small models improve
    # dramatically when they do not have to invent structure, narration and image prompts at once.
    profile = _style_profile(project.style)
    blueprint_schema = {
        "type": "object",
        "properties": {
            "hook": {"type": "string"},
            "story_promise": {"type": "string"},
            "beats": {
                "type": "array",
                "minItems": scene_count,
                "maxItems": scene_count,
                "items": {"type": "string"},
            },
        },
        "required": ["hook", "story_promise", "beats"],
    }
    _progress(self, 8, "Story Director • building hook and retention arc")
    blueprint_prompt = f"""You are a senior short-form story producer. Build the story architecture BEFORE writing narration.

TOPIC / RESEARCH CONTEXT:
{project.topic}

STYLE: {profile}
TARGET: {project.target_seconds} seconds, about {target_words} spoken words
VISUAL BEATS: exactly {scene_count}

HOOK RULES
- Hook in one natural sentence, ideally 6-18 words.
- Start on the most compelling conflict, consequence, contrast, mystery, reversal or concrete detail.
- For a person's story, establish why this person's trajectory matters immediately.
- Do NOT use: Did you know, Imagine this, Picture this, You won't believe, Have you ever wondered, This is the story of, But here's the crazy part, Let that sink in.
- Do not write an empty tease. The hook should contain real information while leaving forward tension.

RETENTION ARC
- Beat 1 earns attention.
- Beat 2 gives only the context needed to understand the story.
- Every later beat changes the situation or adds a distinct fact/consequence. No paraphrased beats.
- Put the strongest turn/reveal near the final third, not immediately after the hook.
- The final beat should land emotionally or intellectually without a CTA or summary paragraph.
- Factual topic: use only information present in the topic/research context; do not invent specifics.

Return only the required JSON."""
    blueprint = _json_call(self, model, blueprint_prompt, blueprint_schema, temperature=0.55)
    hook = " ".join(str(blueprint.get("hook", "")).split()).strip()
    beats = [" ".join(str(x).split()).strip() for x in blueprint.get("beats", [])]
    if len(beats) != scene_count or not all(beats):
        raise RuntimeError("Story Director could not build the requested beat structure")

    draft_schema = {
        "type": "object",
        "properties": {
            "scenes": {
                "type": "array",
                "minItems": scene_count,
                "maxItems": scene_count,
                "items": {
                    "type": "object",
                    "properties": {"narration": {"type": "string"}},
                    "required": ["narration"],
                },
            },
        },
        "required": ["scenes"],
    }
    beat_block = "\n".join(f"{i + 1}. {beat}" for i, beat in enumerate(beats))
    _progress(self, 9, "Story Director • writing spoken first draft")
    draft_prompt = f"""Write the narration from this approved story architecture.
TOPIC: {project.topic}
STYLE: {profile}
TARGET: approximately {target_words} total spoken words across exactly {scene_count} entries.
APPROVED HOOK IDEA: {hook}
STORY PROMISE: {blueprint.get('story_promise', '')}

BEATS:
{beat_block}

SPOKEN-WRITING RULES
- Sound like one smart person telling another person something worth hearing.
- Start immediately. No title-reading, intro, greeting, channel language or setup filler.
- Use the approved hook idea naturally in entry 1. Do not turn it into clickbait.
- One new idea per beat. Never restate the previous beat in new words.
- Prefer plain verbs and concrete nouns over dramatic adjectives.
- Use contractions naturally. Vary sentence length and punctuation.
- A short fragment can add rhythm occasionally; fragments should not become the whole style.
- Avoid symmetrical AI prose, stacked rhetorical questions and repeated "not X, but Y" constructions.
- Avoid these phrases entirely: {', '.join(_BANNED_CLICHES)}.
- Do not add facts absent from the topic/research context.
- Ending: one strong landing line, not "in conclusion", not a recap, not a CTA.

Return only JSON."""
    draft = _json_call(self, model, draft_prompt, draft_schema, temperature=0.58)
    narrations = [" ".join(str(x.get("narration", "")).split()).strip() for x in draft.get("scenes", [])]
    if len(narrations) != scene_count or not all(narrations):
        raise RuntimeError("Story Director returned an incomplete narration draft")

    _progress(self, 11, "Humanizer • removing AI cadence and canned phrasing")
    human_prompt = f"""You are the final human script editor for a spoken TikTok/Reels narration.
Rewrite the draft below so it sounds genuinely spoken, not AI-written.

TOPIC: {project.topic}
STYLE: {profile}
TARGET: {target_words} words total, acceptable range {int(target_words * .92)}-{int(target_words * 1.08)}
ENTRIES: exactly {scene_count}

EDITING TEST
Ask of every sentence: would a real narrator naturally say this out loud in one take?

RULES
- Preserve every supported fact and the story order. Invent nothing.
- Make the FIRST sentence an immediate, specific hook. No generic question or creator cliché.
- Remove formal transitions, filler, repeated conclusions and over-explaining.
- Break long written sentences into speech-sized thoughts where useful.
- Vary rhythm; do not make every line the same length or use the same opening pattern.
- Avoid em-dash overload. Prefer periods, commas and occasional ellipses only when natural for speech.
- Remove robotic contrast templates like "It wasn't just X—it was Y" when a simpler sentence sounds better.
- Do not intensify facts with unsupported adjectives.
- Each entry must advance to a new beat.
- Final entry must land. No CTA and no summary paragraph.
- Forbidden canned phrases: {', '.join(_BANNED_CLICHES)}.

DRAFT:
""" + "\n".join(f"{i + 1}. {text}" for i, text in enumerate(narrations))
    human = _json_call(self, model, human_prompt, draft_schema, temperature=0.42)
    candidate = [" ".join(str(x.get("narration", "")).split()).strip() for x in human.get("scenes", [])]
    if len(candidate) == scene_count and all(candidate):
        narrations = candidate

    problems = _script_problems(narrations, target_words)
    if problems:
        _progress(self, 12, "Script QA • repairing " + "; ".join(problems[:2]))
        repair_prompt = f"""Repair ONLY the problems listed below in this spoken short-form narration.
TOPIC: {project.topic}
FACT RULE: preserve facts and add no new factual claims.
TARGET WORDS: {target_words}, acceptable {int(target_words * .92)}-{int(target_words * 1.08)}
KEEP EXACTLY {scene_count} entries.
PROBLEMS: {'; '.join(problems)}

Make the hook specific and natural, remove canned AI cadence, keep every beat distinct, and make the final line land without a CTA.
Return only JSON.

SCRIPT:
""" + "\n".join(f"{i + 1}. {text}" for i, text in enumerate(narrations))
        repaired = _json_call(self, model, repair_prompt, draft_schema, temperature=0.46)
        fixed = [" ".join(str(x.get("narration", "")).split()).strip() for x in repaired.get("scenes", [])]
        if len(fixed) == scene_count and all(fixed):
            narrations = fixed

    final_problems = _script_problems(narrations, target_words)
    word_count = _word_count(" ".join(narrations))
    project.script_quality_summary = (
        f"Story Director v2 • {word_count} words • hook {'PASS' if _hook_ok(narrations[0]) else 'CHECK'}"
        + (" • QA: " + "; ".join(final_problems[:2]) if final_problems else " • naturalness QA PASS")
    )
    _progress(self, 12, project.script_quality_summary)

    _progress(self, 13, "Narration locked • directing scene-specific visuals")
    title, anchor, continuity, prompts = _visual_plan(self, project, model, narrations)
    project.title = title or project.topic[:100]
    scenes = _build_scenes(project, narrations, prompts, anchor, continuity)
    project.script = " ".join(narrations).strip()
    return project.script, scenes


def mock_story_generate(self, project: Project, scene_count: int):
    mode = getattr(project, "script_mode", "AI Script")
    if mode not in {"Custom Script", "AI Polish My Script"}:
        return _ORIGINAL_MOCK_GENERATE(self, project, scene_count)
    source = (getattr(project, "custom_script", "") or "").strip()
    if not source:
        raise RuntimeError("Paste a script in Create before using Custom Script mode.")
    narrations = split_custom_script(source, scene_count)
    prompts = [f"Mock visual beat for: {text[:100]}" for text in narrations]
    scenes = [Scene(index=i + 1, narration=n, image_prompt=p, duration=max(1.0, project.target_seconds / len(narrations))) for i, (n, p) in enumerate(zip(narrations, prompts))]
    project.script = " ".join(narrations)
    project.script_model_used = "Mock"
    project.script_quality_summary = "Custom script test mode"
    return project.script, scenes


_ORIGINAL_SCRIPT_GENERATE = services.ScriptService.generate
_ORIGINAL_MOCK_GENERATE = services.MockScriptService.generate


def install() -> None:
    services.ScriptService.generate = story_director_generate
    services.MockScriptService.generate = mock_story_generate
