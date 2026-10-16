from __future__ import annotations

from dataclasses import asdict, dataclass
from pathlib import Path
import base64
import html
import json
import os
import re
import subprocess
import urllib.error
import urllib.parse
import urllib.request

from PySide6.QtCore import Qt, QUrl
from PySide6.QtGui import QDesktopServices
from PySide6.QtWidgets import (
    QComboBox,
    QGridLayout,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMessageBox,
    QPlainTextEdit,
    QVBoxLayout,
)

from . import pipeline, services, ui, v070_pipeline, v070_voice, v071_pipeline
from .cloud_secrets import delete_secret, get_secret, set_secret
from .config import APP_DIR, find_executable
from .models import Scene


OPENAI_SECRET = "OPENAI_API_KEY"
ELEVEN_SECRET = "ELEVENLABS_API_KEY"
ELEVEN_ENGINE = "ElevenLabs Cloud"
CLOUD_SETTINGS_FILE = APP_DIR / "cloud.json"
_OPENAI_IMAGE_ACTIVE = False


@dataclass(slots=True)
class CloudSettings:
    openai_text_model: str = "gpt-5-mini"
    openai_image_model: str = "gpt-image-1"
    openai_image_quality: str = "medium"
    eleven_voice_id: str = "JBFqnCBsd6RMkjVDRZzb"
    eleven_voice_name: str = "George"
    eleven_model_id: str = "eleven_v4"
    eleven_stability: float = 0.42
    eleven_similarity: float = 0.78


def load_cloud_settings() -> CloudSettings:
    if not CLOUD_SETTINGS_FILE.exists():
        return CloudSettings()
    try:
        raw = json.loads(CLOUD_SETTINGS_FILE.read_text(encoding="utf-8"))
        allowed = CloudSettings.__dataclass_fields__.keys()
        return CloudSettings(**{k: v for k, v in raw.items() if k in allowed})
    except Exception:
        return CloudSettings()


def save_cloud_settings(value: CloudSettings) -> None:
    APP_DIR.mkdir(parents=True, exist_ok=True)
    CLOUD_SETTINGS_FILE.write_text(json.dumps(asdict(value), indent=2), encoding="utf-8")


def _http_json(url: str, *, method: str = "GET", payload: dict | None = None, headers: dict[str, str] | None = None, timeout: int = 180) -> dict:
    body = None if payload is None else json.dumps(payload).encode("utf-8")
    request = urllib.request.Request(url, data=body, method=method)
    request.add_header("User-Agent", "ZeroReels/0.11")
    if payload is not None:
        request.add_header("Content-Type", "application/json")
    for key, value in (headers or {}).items():
        request.add_header(key, value)
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            raw = response.read()
        return json.loads(raw.decode("utf-8"))
    except urllib.error.HTTPError as exc:
        detail = exc.read().decode("utf-8", errors="replace")[-1800:]
        raise RuntimeError(f"HTTP {exc.code}: {detail}") from exc
    except urllib.error.URLError as exc:
        raise RuntimeError(f"Network request failed: {exc.reason}") from exc


def _http_bytes(url: str, *, payload: dict, headers: dict[str, str], timeout: int = 600) -> bytes:
    request = urllib.request.Request(url, data=json.dumps(payload).encode("utf-8"), method="POST")
    request.add_header("User-Agent", "ZeroReels/0.11")
    request.add_header("Content-Type", "application/json")
    for key, value in headers.items():
        request.add_header(key, value)
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            return response.read()
    except urllib.error.HTTPError as exc:
        detail = exc.read().decode("utf-8", errors="replace")[-1800:]
        raise RuntimeError(f"HTTP {exc.code}: {detail}") from exc
    except urllib.error.URLError as exc:
        raise RuntimeError(f"Network request failed: {exc.reason}") from exc


def _openai_headers(key: str | None = None) -> dict[str, str]:
    key = (key or get_secret(OPENAI_SECRET)).strip()
    if not key:
        raise RuntimeError("OpenAI is not connected. Open Settings → OpenAI / ChatGPT and connect an API key.")
    return {"Authorization": f"Bearer {key}"}


def _eleven_headers(key: str | None = None) -> dict[str, str]:
    key = (key or get_secret(ELEVEN_SECRET)).strip()
    if not key:
        raise RuntimeError("ElevenLabs is not connected. Open Settings → ElevenLabs and connect an API key.")
    return {"xi-api-key": key}


def validate_openai_key(key: str) -> str:
    data = _http_json("https://api.openai.com/v1/models", headers=_openai_headers(key), timeout=20)
    count = len(data.get("data", []))
    return f"Connected • {count} models visible" if count else "Connected"


def validate_eleven_key(key: str) -> str:
    data = _http_json("https://api.elevenlabs.io/v1/user", headers=_eleven_headers(key), timeout=20)
    sub = data.get("subscription", {}) or {}
    tier = str(sub.get("tier") or sub.get("status") or "account")
    used = sub.get("character_count")
    limit = sub.get("character_limit")
    if isinstance(used, int) and isinstance(limit, int) and limit:
        return f"Connected • {tier} • {used:,}/{limit:,} credits used"
    return f"Connected • {tier}"


def list_eleven_voices(key: str | None = None) -> list[tuple[str, str]]:
    headers = _eleven_headers(key)
    for url in (
        "https://api.elevenlabs.io/v2/voices?page_size=100&include_total_count=true",
        "https://api.elevenlabs.io/v1/voices",
    ):
        try:
            data = _http_json(url, headers=headers, timeout=30)
            rows = data.get("voices", [])
            result = []
            for row in rows:
                voice_id = str(row.get("voice_id") or "").strip()
                name = str(row.get("name") or voice_id).strip()
                if voice_id:
                    result.append((name, voice_id))
            if result:
                return result
        except Exception:
            continue
    return []


def _extract_response_text(data: dict) -> str:
    direct = data.get("output_text")
    if isinstance(direct, str) and direct.strip():
        return direct.strip()
    chunks: list[str] = []
    for item in data.get("output", []) or []:
        for content in item.get("content", []) or []:
            text = content.get("text")
            if isinstance(text, str) and text.strip():
                chunks.append(text)
    if chunks:
        return "\n".join(chunks).strip()
    raise RuntimeError("OpenAI returned no text output")


def _openai_json(prompt: str, schema: dict, name: str, *, model: str | None = None, timeout: int = 600) -> dict:
    cloud = load_cloud_settings()
    payload = {
        "model": model or cloud.openai_text_model,
        "input": prompt,
        "text": {
            "format": {
                "type": "json_schema",
                "name": name,
                "schema": schema,
                "strict": True,
            }
        },
        "max_output_tokens": 12000,
    }
    data = _http_json(
        "https://api.openai.com/v1/responses",
        method="POST",
        payload=payload,
        headers=_openai_headers(),
        timeout=timeout,
    )
    try:
        return json.loads(_extract_response_text(data))
    except json.JSONDecodeError as exc:
        raise RuntimeError("OpenAI returned invalid structured script data") from exc


def _role_for(index: int, count: int) -> str:
    if index == 0:
        return "Hook"
    if index == count - 1:
        return "Landing"
    ratio = index / max(1, count - 1)
    if ratio < 0.22:
        return "Establishing"
    if ratio < 0.45:
        return "Action"
    if ratio < 0.65:
        return "Escalation"
    if ratio < 0.82:
        return "Peak"
    return "Aftermath"


def _words(text: str) -> list[str]:
    return re.findall(r"[A-Za-z0-9][A-Za-z0-9'’-]*", text or "")


def _broll_query(topic: str, narration: str) -> str:
    stop = {"the", "and", "that", "this", "with", "from", "into", "were", "was", "have", "has", "what", "when", "where", "would", "could", "about", "because", "their", "there", "then"}
    picks: list[str] = []
    for word in _words(narration):
        key = word.lower()
        if len(key) < 3 or key in stop:
            continue
        if key not in {x.lower() for x in picks}:
            picks.append(word)
        if len(picks) >= 4:
            break
    subject = " ".join(_words(topic)[:4])
    return " ".join([subject, *picks]).strip()[:100]


def _split_exact(text: str, count: int) -> list[str]:
    clean = " ".join((text or "").split()).strip()
    if not clean:
        return [""] * count
    sentences = [s.strip() for s in re.split(r"(?<=[.!?…])\s+", clean) if s.strip()]
    if len(sentences) >= count:
        target = max(1, len(_words(clean)) / count)
        groups: list[str] = []
        current: list[str] = []
        current_words = 0
        for sentence in sentences:
            remaining_sentences = len(sentences) - sentences.index(sentence)
            remaining_groups = count - len(groups)
            if current and current_words >= target and remaining_sentences >= remaining_groups:
                groups.append(" ".join(current))
                current = []
                current_words = 0
            current.append(sentence)
            current_words += len(_words(sentence))
        if current:
            groups.append(" ".join(current))
        while len(groups) > count:
            groups[-2] = (groups[-2] + " " + groups[-1]).strip()
            groups.pop()
        if len(groups) == count:
            return groups
    words = clean.split()
    result: list[str] = []
    start = 0
    for i in range(count):
        end = round(len(words) * (i + 1) / count)
        result.append(" ".join(words[start:end]).strip())
        start = end
    return result


def _custom_script(project, scene_count: int) -> tuple[str, list[Scene]]:
    text = (getattr(project, "custom_script", "") or project.script or "").strip()
    if not text:
        raise RuntimeError("Custom Script is empty")
    chunks = _split_exact(text, scene_count)
    scenes: list[Scene] = []
    for i, narration in enumerate(chunks):
        role = _role_for(i, scene_count)
        prompt = (
            f"{project.style}. {role} shot illustrating this narration: {narration}. "
            "Cinematic documentary composition, concrete subject and environment, no readable text, no captions, no logo, no watermark."
        )
        scene = Scene(i + 1, narration, prompt, max(2.0, project.target_seconds / scene_count))
        scene.shot_role = role
        scene.source_query = "Planned B-roll: " + _broll_query(project.topic, narration)
        scenes.append(scene)
    project.title = project.topic.strip()[:100] or "Custom Reel"
    project.script_model_used = "Custom Script"
    project.script_quality_summary = "Custom narration preserved • OpenAI writer bypassed"
    return text, scenes


def chatgpt_generate(self, project, scene_count: int):
    mode = getattr(project, "script_mode", "ChatGPT Script") or "ChatGPT Script"
    if mode == "Custom Script":
        return _custom_script(project, scene_count)

    count = max(3, int(scene_count))
    scene_schema = {
        "type": "object",
        "properties": {
            "narration": {"type": "string"},
            "image_prompt": {"type": "string"},
            "broll_query": {"type": "string"},
            "shot_role": {"type": "string"},
        },
        "required": ["narration", "image_prompt", "broll_query", "shot_role"],
        "additionalProperties": False,
    }
    schema = {
        "type": "object",
        "properties": {
            "title": {"type": "string"},
            "scenes": {"type": "array", "minItems": count, "maxItems": count, "items": scene_schema},
        },
        "required": ["title", "scenes"],
        "additionalProperties": False,
    }
    research = (getattr(project, "research_context", "") or "").strip()
    target_words = max(45, round(float(project.target_seconds) * 2.35))
    prompt = f"""Write the complete narration and visual plan for a high-retention short-form video.

TOPIC: {project.topic}
STYLE: {project.style}
TARGET RUNTIME: {project.target_seconds} seconds
TARGET SPOKEN WORDS: about {target_words}
SCENES: exactly {count}
{('RESEARCH CONTEXT (prefer this over unsupported assumptions): ' + research) if research else ''}

Write this directly. There is no later Story Director pass.

SCRIPT RULES
- Scene 1 opens on the strongest concrete fact, consequence, conflict, mystery, reversal, or surprising question. No greetings or generic creator hooks.
- By scene 2 the viewer understands the premise and why it matters.
- Every scene adds new information; never paraphrase the previous scene just to fill time.
- Build clear cause-and-effect and place the strongest reveal/payoff near the final third when the subject supports it.
- Natural spoken English: contractions, varied sentence length, specific nouns, plain verbs, minimal filler.
- End with a memorable landing line, not a recap or generic CTA.
- For factual topics, do not invent quotations, dates, statistics, names, or events. If uncertain, phrase cautiously.

EDITING RULES
- image_prompt describes a single useful visual beat, not captions or typography. Keep it specific enough for an image generator.
- broll_query is 2-7 literal searchable words for real footage: named people, places, objects, machines, actions, or environments.
- shot_role must be one of Hook, Establishing, Action, Detail, Escalation, Peak, Aftermath, Landing.
- Adjacent scenes should visibly differ in scale, angle, location, activity, or subject.

Return only the required structured data."""
    data = _openai_json(prompt, schema, "zeroreels_script")
    rows = data.get("scenes", [])
    if len(rows) != count:
        raise RuntimeError(f"OpenAI returned {len(rows)} scenes; expected {count}")
    scenes: list[Scene] = []
    allowed_roles = {"Hook", "Establishing", "Action", "Detail", "Escalation", "Peak", "Aftermath", "Landing"}
    for i, row in enumerate(rows):
        narration = " ".join(str(row.get("narration", "")).split()).strip()
        image_prompt = " ".join(str(row.get("image_prompt", "")).split()).strip()
        if not narration or not image_prompt:
            raise RuntimeError("OpenAI returned an incomplete scene")
        scene = Scene(i + 1, narration, image_prompt, max(2.0, project.target_seconds / count))
        role = str(row.get("shot_role") or "").strip()
        scene.shot_role = role if role in allowed_roles else _role_for(i, count)
        query = " ".join(str(row.get("broll_query") or "").split()).strip() or _broll_query(project.topic, narration)
        scene.source_query = "Planned B-roll: " + query[:120]
        scenes.append(scene)
    project.title = " ".join(str(data.get("title") or project.topic).split()).strip()[:100]
    script = " ".join(scene.narration for scene in scenes).strip()
    project.script = script
    cloud = load_cloud_settings()
    project.script_model_used = cloud.openai_text_model
    project.script_quality_summary = f"ChatGPT/OpenAI direct writer • {len(_words(script))} words"
    return script, scenes


def _tagless_words(text: str) -> list[str]:
    value = re.sub(r"\[[^\]]+\]", " ", text or "")
    return [w.casefold() for w in re.findall(r"[A-Za-z0-9]+(?:['’][A-Za-z0-9]+)?", value)]


def _fallback_tag(scene) -> str:
    text = " ".join((scene.narration or "").split()).strip()
    role = (scene.shot_role or "").casefold()
    if role == "hook":
        return f"[curious] {text}"
    if role in {"escalation", "peak"}:
        return f"[serious] {text}"
    if role == "landing":
        return f"[sighs] {text}"
    return text


def build_elevenlabs_script(project, *, progress=None) -> list[str]:
    count = len(project.scenes)
    if not count:
        return []
    scene_schema = {
        "type": "object",
        "properties": {"text": {"type": "string"}},
        "required": ["text"],
        "additionalProperties": False,
    }
    schema = {
        "type": "object",
        "properties": {"scenes": {"type": "array", "minItems": count, "maxItems": count, "items": scene_schema}},
        "required": ["scenes"],
        "additionalProperties": False,
    }
    source = "\n".join(f"{i + 1}. [{scene.shot_role or _role_for(i, count)}] {scene.narration}" for i, scene in enumerate(project.scenes))
    prompt = f"""Prepare this narration specifically for ElevenLabs Eleven v4 performance.

Add sparse native ElevenLabs audio tags in SQUARE BRACKETS. Good examples include [curious], [whispers], [shouts], [gasps], [sighs], [laughs], [excited], [serious], [pause], and [long pause].

Rules:
- Preserve every spoken word in every scene exactly. Do not rewrite facts, phrasing, names, numbers, or sentence order.
- Tags are directions/nonverbal reactions only; they must not add spoken narration.
- Use tags only where they improve the delivery. Usually 0-2 tags per scene. Do not make every sentence melodramatic.
- A reaction tag such as [gasps] is okay when the story genuinely calls for it.
- Do not use parentheses for direction. Do not use SSML.
- Return exactly {count} scene strings.

NARRATION:\n{source}"""
    try:
        if progress:
            progress(18, "ChatGPT • directing ElevenLabs emotion and reaction tags")
        data = _openai_json(prompt, schema, "elevenlabs_performance")
        rows = data.get("scenes", [])
        tagged = [" ".join(str(row.get("text", "")).split()).strip() for row in rows]
        if len(tagged) != count:
            raise RuntimeError("Incomplete ElevenLabs performance script")
        for scene, value in zip(project.scenes, tagged):
            if _tagless_words(value) != _tagless_words(scene.narration):
                raise RuntimeError("Performance pass changed narration words")
        return tagged
    except Exception:
        return [_fallback_tag(scene) for scene in project.scenes]


def _eleven_text_for_model(tagged: str, model_id: str) -> str:
    if model_id in {"eleven_v4", "eleven_v4_turbo", "eleven_v3"}:
        return tagged
    value = re.sub(r"\[long pause\]", '<break time="1.2s" />', tagged, flags=re.IGNORECASE)
    value = re.sub(r"\[pause\]", '<break time="0.6s" />', value, flags=re.IGNORECASE)
    value = re.sub(r"\[[^\]]+\]", "", value)
    return " ".join(value.split())


def _ffmpeg(settings) -> str:
    path = find_executable(getattr(settings, "ffmpeg_exe", ""), "ffmpeg")
    if path:
        return path
    try:
        import imageio_ffmpeg
        return imageio_ffmpeg.get_ffmpeg_exe()
    except Exception as exc:
        raise RuntimeError("FFmpeg is required to convert ElevenLabs narration audio") from exc


class ElevenLabsVoiceService:
    def __init__(self, settings, delivery: str):
        self.settings = settings
        self.delivery = delivery

    def generate(self, project, out_dir: Path, progress=None) -> Path:
        cloud = load_cloud_settings()
        if not cloud.eleven_voice_id:
            raise RuntimeError("Choose an ElevenLabs voice in Settings first")
        tagged = build_elevenlabs_script(project, progress=progress)
        if not tagged:
            raise RuntimeError("Narration is empty")
        model_id = cloud.eleven_model_id or "eleven_v4"
        rendered = [_eleven_text_for_model(value, model_id) for value in tagged]
        separator = " [pause] " if model_id in {"eleven_v4", "eleven_v4_turbo", "eleven_v3"} else ' <break time="0.35s" /> '
        text = separator.join(rendered)
        if project.output_dir:
            try:
                script_path = Path(project.output_dir) / "elevenlabs_script.txt"
                script_path.write_text("\n\n".join(f"Scene {i + 1}:\n{value}" for i, value in enumerate(rendered)), encoding="utf-8")
            except Exception:
                pass
        if progress:
            progress(20, f"ElevenLabs • {cloud.eleven_voice_name or cloud.eleven_voice_id} • {model_id}")
        query = urllib.parse.urlencode({"output_format": "mp3_44100_128"})
        url = f"https://api.elevenlabs.io/v1/text-to-speech/{urllib.parse.quote(cloud.eleven_voice_id)}?{query}"
        payload = {
            "text": text,
            "model_id": model_id,
            "voice_settings": {
                "stability": max(0.0, min(1.0, float(cloud.eleven_stability))),
                "similarity_boost": max(0.0, min(1.0, float(cloud.eleven_similarity))),
            },
        }
        audio = _http_bytes(url, payload=payload, headers=_eleven_headers(), timeout=900)
        out_dir.mkdir(parents=True, exist_ok=True)
        mp3 = out_dir / "narration_elevenlabs.mp3"
        mp3.write_bytes(audio)
        if mp3.stat().st_size < 1000:
            raise RuntimeError("ElevenLabs returned an invalid audio file")
        target = out_dir / "narration.wav"
        proc = subprocess.run(
            [_ffmpeg(self.settings), "-y", "-i", str(mp3), "-ac", "1", "-ar", "44100", "-c:a", "pcm_s16le", str(target)],
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
        )
        if proc.returncode != 0 or not target.exists() or target.stat().st_size < 1000:
            detail = proc.stderr.decode("utf-8", errors="replace")[-1200:]
            raise RuntimeError("Could not convert ElevenLabs audio to WAV: " + detail)
        duration = v070_voice._wav_duration(target)
        v070_voice.apply_scene_timing(project, duration, self.delivery)
        project.actual_seconds = round(duration, 2)
        project.voice_engine_used = ELEVEN_ENGINE
        project.voice_delivery = self.delivery
        if progress:
            progress(29, f"ElevenLabs narration ready • {duration:.1f}s")
        return target


class OpenAIImageService:
    def __init__(self, settings):
        self.settings = settings

    def generate(self, scene, out_dir: Path, fmt: str) -> Path:
        cloud = load_cloud_settings()
        size = {"9:16": "1024x1536", "16:9": "1536x1024", "1:1": "1024x1024"}.get(fmt, "1024x1536")
        prompt = (
            f"Create one polished {fmt} visual for a short-form video. {scene.image_prompt} "
            "No captions, no visible UI, no watermark, no logo, and avoid accidental readable text unless the scene explicitly requires it."
        )
        payload = {
            "model": cloud.openai_image_model or "gpt-image-1",
            "prompt": prompt,
            "size": size,
            "quality": cloud.openai_image_quality or "medium",
            "background": "opaque",
            "output_format": "png",
        }
        data = _http_json(
            "https://api.openai.com/v1/images/generations",
            method="POST",
            payload=payload,
            headers=_openai_headers(),
            timeout=900,
        )
        rows = data.get("data", []) or []
        if not rows:
            raise RuntimeError("OpenAI image generation returned no image")
        row = rows[0]
        if row.get("b64_json"):
            raw = base64.b64decode(row["b64_json"])
        elif row.get("url"):
            with urllib.request.urlopen(str(row["url"]), timeout=120) as response:
                raw = response.read()
        else:
            raise RuntimeError("OpenAI image response had no image bytes")
        out_dir.mkdir(parents=True, exist_ok=True)
        target = out_dir / f"scene_{scene.index:03d}_openai.png"
        target.write_bytes(raw)
        scene.source_type = "OpenAI Image"
        scene.source_query = prompt[:240]
        return target


def openai_runtime_rewrite(settings, project, actual_seconds: float, progress=None, pass_index: int = 1) -> bool:
    if getattr(project, "script_mode", "ChatGPT Script") == "Custom Script":
        if progress:
            progress(31, f"Custom Script lock • preserving wording • {actual_seconds:.1f}s measured")
        return False
    target = float(project.target_seconds)
    if target <= 0 or actual_seconds <= 0 or 0.95 <= target / actual_seconds <= 1.05:
        return False
    count = len(project.scenes)
    scene_schema = {
        "type": "object",
        "properties": {"narration": {"type": "string"}},
        "required": ["narration"],
        "additionalProperties": False,
    }
    schema = {
        "type": "object",
        "properties": {"scenes": {"type": "array", "minItems": count, "maxItems": count, "items": scene_schema}},
        "required": ["scenes"],
        "additionalProperties": False,
    }
    direction = "expand" if actual_seconds < target else "tighten"
    draft = "\n".join(f"{i + 1}. {scene.narration}" for i, scene in enumerate(project.scenes))
    prompt = f"""Adjust this already-approved narration so spoken runtime moves from {actual_seconds:.1f}s toward {target:.1f}s.

{direction.upper()} naturally. Keep exactly {count} scenes and keep each scene's purpose/order so its existing visual remains valid.
Preserve facts, names, numbers, uncertainty and causal meaning. Do not invent facts. Remove redundancy before useful meaning when shortening; deepen only existing facts when expanding. Natural speech, no filler, no CTA.

DRAFT:\n{draft}"""
    try:
        if progress:
            progress(31, f"ChatGPT runtime lock • pass {pass_index} • {actual_seconds:.1f}s → {target:.0f}s")
        data = _openai_json(prompt, schema, "zeroreels_runtime")
        rows = data.get("scenes", [])
        values = [" ".join(str(row.get("narration", "")).split()).strip() for row in rows]
        if len(values) != count or not all(values):
            return False
        for scene, text in zip(project.scenes, values):
            scene.narration = text
        project.script = " ".join(values)
        project.runtime_rewrites += 1
        return True
    except Exception:
        return False


_PREVIOUS_PIPELINE_RUN = None
_PREVIOUS_VOICE_RESOLVER = None
_PREVIOUS_DIAGNOSTICS = None
_PREVIOUS_CREATE_PAGE = None
_PREVIOUS_SETUP_PAGE = None
_PREVIOUS_SETTINGS_PAGE = None
_PREVIOUS_SAVE_SETTINGS = None
_PREVIOUS_OPTIONS = None
_PREVIOUS_GENERATE = None
_PREVIOUS_SIDEBAR = None


def cloud_pipeline_run(self, project, options, progress=lambda value, text: None):
    global _OPENAI_IMAGE_ACTIVE
    use_openai_images = not bool(getattr(options, "mock_mode", False)) and getattr(options, "image_source_mode", "") == "OpenAI Images"
    old_service = services.ComfyImageService
    _OPENAI_IMAGE_ACTIVE = use_openai_images
    if use_openai_images:
        services.ComfyImageService = OpenAIImageService
    try:
        return _PREVIOUS_PIPELINE_RUN(self, project, options, progress)
    finally:
        services.ComfyImageService = old_service
        _OPENAI_IMAGE_ACTIVE = False


def cloud_voice_service_for(settings, engine: str, delivery: str, mock_mode: bool = False):
    if mock_mode:
        return services.MockVoiceService()
    if engine == ELEVEN_ENGINE:
        return ElevenLabsVoiceService(settings, delivery)
    return _PREVIOUS_VOICE_RESOLVER(settings, engine, delivery, mock_mode)


def cloud_preflight(self, options) -> None:
    missing: list[str] = []
    script_mode = getattr(options, "script_mode", "ChatGPT Script")
    if script_mode != "Custom Script" and not get_secret(OPENAI_SECRET):
        missing.append("OpenAI / ChatGPT connection")
    if _OPENAI_IMAGE_ACTIVE and not get_secret(OPENAI_SECRET):
        missing.append("OpenAI image connection")
    if not _OPENAI_IMAGE_ACTIVE and getattr(options, "image_source_mode", "AI Generated") != "Real Web Images":
        try:
            services.ComfyImageService(self.settings).validate_server()
        except Exception:
            missing.append("ComfyUI / FLUX (or choose OpenAI Images)")
    engine = getattr(options, "voice_engine", "Kokoro Directed")
    if engine == ELEVEN_ENGINE:
        if not get_secret(ELEVEN_SECRET):
            missing.append("ElevenLabs connection")
    elif engine in {"Kokoro Directed", "Kokoro Classic"}:
        try:
            model = Path(self.settings.kokoro_model_path).expanduser()
            voices = Path(self.settings.kokoro_voices_path).expanduser()
            if not model.exists() or not voices.exists():
                missing.append("Kokoro voice files")
        except Exception:
            missing.append("Kokoro voice files")
    if not _ffmpeg(self.settings):
        missing.append("FFmpeg")
    if missing:
        raise RuntimeError("Generation is not ready yet. Open Settings/Setup and complete:\n• " + "\n• ".join(missing))


def cloud_diagnostics(settings):
    rows = [row for row in _PREVIOUS_DIAGNOSTICS(settings) if row[0] not in {"Ollama", "Script model"}]
    openai = bool(get_secret(OPENAI_SECRET))
    eleven = bool(get_secret(ELEVEN_SECRET))
    cloud = load_cloud_settings()
    rows.insert(0, ("OpenAI / ChatGPT", openai, f"{cloud.openai_text_model} • {'connected' if openai else 'not connected'}"))
    rows.insert(1, ("OpenAI Images", openai, f"{cloud.openai_image_model} • optional visual source"))
    rows.insert(2, ("ElevenLabs", eleven, f"{cloud.eleven_voice_name or cloud.eleven_voice_id} • {'connected' if eleven else 'optional / not connected'}"))
    return rows


def _connect_openai(self):
    key = self.openai_key_edit.text().strip()
    if not key:
        QMessageBox.information(self, "OpenAI", "Paste an OpenAI API key first.")
        return
    try:
        status = validate_openai_key(key)
        set_secret(OPENAI_SECRET, key)
        self.openai_key_edit.clear()
        self.openai_key_edit.setPlaceholderText("Connected securely in Windows Credential Manager")
        self.openai_status.setText(status)
        self.openai_status.setStyleSheet(f"color:{ui.ACCENT};")
    except Exception as exc:
        QMessageBox.critical(self, "OpenAI connection", str(exc))


def _disconnect_openai(self):
    delete_secret(OPENAI_SECRET)
    self.openai_status.setText("Not connected")
    self.openai_status.setStyleSheet(f"color:{ui.MUTED};")


def _connect_eleven(self):
    key = self.eleven_key_edit.text().strip()
    if not key:
        QMessageBox.information(self, "ElevenLabs", "Paste an ElevenLabs API key first.")
        return
    try:
        status = validate_eleven_key(key)
        set_secret(ELEVEN_SECRET, key)
        self.eleven_key_edit.clear()
        self.eleven_key_edit.setPlaceholderText("Connected securely in Windows Credential Manager")
        self.eleven_status.setText(status)
        self.eleven_status.setStyleSheet(f"color:{ui.ACCENT};")
        _refresh_eleven_voices(self)
        if hasattr(self, "voice_engine_box"):
            self.voice_engine_box.setCurrentText(ELEVEN_ENGINE)
    except Exception as exc:
        QMessageBox.critical(self, "ElevenLabs connection", str(exc))


def _disconnect_eleven(self):
    delete_secret(ELEVEN_SECRET)
    self.eleven_status.setText("Not connected")
    self.eleven_status.setStyleSheet(f"color:{ui.MUTED};")


def _refresh_eleven_voices(self):
    cloud = load_cloud_settings()
    try:
        rows = list_eleven_voices()
        self.eleven_voice_box.clear()
        if not rows:
            self.eleven_voice_box.addItem(cloud.eleven_voice_name or cloud.eleven_voice_id, cloud.eleven_voice_id)
            self.eleven_status.setText(self.eleven_status.text() + " • voice listing unavailable on this account; current voice kept")
            return
        for name, voice_id in rows:
            self.eleven_voice_box.addItem(name, voice_id)
        index = self.eleven_voice_box.findData(cloud.eleven_voice_id)
        self.eleven_voice_box.setCurrentIndex(index if index >= 0 else 0)
    except Exception as exc:
        QMessageBox.warning(self, "ElevenLabs voices", str(exc))


def sidebar_v110(self):
    frame = _PREVIOUS_SIDEBAR(self)
    for label in frame.findChildren(QLabel):
        if label.text().startswith("v0."):
            label.setText("v0.11 CLOUD")
            label.setMaximumWidth(126)
            break
    return frame


def create_page_v110(self):
    page = _PREVIOUS_CREATE_PAGE(self)
    body = None
    scroll = getattr(self, "create_scroll_area", None)
    if scroll is not None and scroll.widget() is not None:
        body = scroll.widget().layout()
    if not isinstance(body, QVBoxLayout):
        return page

    script_card = ui.Card()
    grid = QGridLayout(script_card)
    grid.setContentsMargins(20, 18, 20, 18)
    grid.setHorizontalSpacing(14)
    grid.setVerticalSpacing(9)
    title = QLabel("ChatGPT Script")
    title.setObjectName("Section")
    note = QLabel("ChatGPT/OpenAI is now the default writer. There is no separate Story Director pass. Custom Script keeps your own narration instead.")
    note.setObjectName("Hint"); note.setWordWrap(True)
    grid.addWidget(title, 0, 0, 1, 2)
    grid.addWidget(note, 1, 0, 1, 2)
    grid.addWidget(QLabel("Script source"), 2, 0)
    self.script_mode_box = QComboBox()
    self.script_mode_box.addItems(["ChatGPT Script", "Custom Script"])
    self.script_mode_box.setCurrentText("ChatGPT Script")
    grid.addWidget(self.script_mode_box, 3, 0, 1, 2)
    self.custom_script_editor = QPlainTextEdit()
    self.custom_script_editor.setPlaceholderText("Optional: switch to Custom Script and paste your finished narration here.")
    self.custom_script_editor.setMinimumHeight(95)
    self.custom_script_editor.setMaximumHeight(170)
    grid.addWidget(self.custom_script_editor, 4, 0, 1, 2)
    self.custom_script_editor.setEnabled(False)
    self.script_mode_box.currentTextChanged.connect(lambda value: self.custom_script_editor.setEnabled(value == "Custom Script"))
    body.insertWidget(1, script_card)

    if hasattr(self, "image_source_box"):
        items = [self.image_source_box.itemText(i) for i in range(self.image_source_box.count())]
        if "OpenAI Images" not in items:
            self.image_source_box.insertItem(0, "OpenAI Images")
        saved = getattr(self.settings, "image_source_mode", "AI Generated")
        if saved in [self.image_source_box.itemText(i) for i in range(self.image_source_box.count())]:
            self.image_source_box.setCurrentText(saved)
        self.image_source_box.setToolTip(
            "OpenAI Images uses GPT Image through your OpenAI API key. AI Generated uses local FLUX. Real Web Images and Hybrid use license-traceable Wikimedia media."
        )

    if hasattr(self, "voice_engine_box"):
        items = [self.voice_engine_box.itemText(i) for i in range(self.voice_engine_box.count())]
        if ELEVEN_ENGINE not in items:
            self.voice_engine_box.insertItem(0, ELEVEN_ENGINE)
        if getattr(self.settings, "voice_engine", "") == ELEVEN_ENGINE:
            self.voice_engine_box.setCurrentText(ELEVEN_ENGINE)

        def voice_changed(value: str) -> None:
            if hasattr(self, "runtime_lock_check"):
                cloud_voice = value == ELEVEN_ENGINE
                self.runtime_lock_check.setEnabled(not cloud_voice)
                if cloud_voice:
                    self.runtime_lock_check.setChecked(False)
                    self.runtime_lock_check.setToolTip("Disabled for ElevenLabs to avoid spending free-tier credits on a second probe/rewrite generation.")
        self.voice_engine_box.currentTextChanged.connect(voice_changed)
        voice_changed(self.voice_engine_box.currentText())
    return page


def setup_page_v110(self):
    page = _PREVIOUS_SETUP_PAGE(self)
    for label in page.findChildren(QLabel):
        text = label.text()
        if text == "Script AI":
            label.setText("OpenAI / ChatGPT")
            card = label.parentWidget()
            if card:
                for child in card.findChildren(QLabel):
                    if "Ollama + Qwen" in child.text() or "Qwen" in child.text():
                        child.setText("ChatGPT/OpenAI writes scripts directly. Connect your API key under Settings; Ollama is no longer used for script generation.")
                for button in card.findChildren(ui.SoftButton):
                    if "Ollama" in button.text() or "Script Model" in button.text() or "Quality Writer" in button.text():
                        button.hide()
                go = ui.SoftButton("Open Cloud Settings")
                go.setObjectName("Primary")
                go.clicked.connect(lambda checked=False: self._navigate(4))
                card.layout().addWidget(go)
        elif text == "Image AI":
            label.setText("Local Image AI (Optional)")
        elif text == "Voice":
            label.setText("Voice Engines")
    for label in page.findChildren(QLabel):
        value = label.text()
        if "Open Ollama" in value:
            label.setText("Connect OpenAI/ElevenLabs in Settings. Local ComfyUI and Kokoro remain optional when you prefer fully local visuals or voice.")
    return page


def settings_page_v110(self):
    page = _PREVIOUS_SETTINGS_PAGE(self)
    cards = page.findChildren(ui.Card)
    if not cards:
        return page
    grid = cards[0].layout()
    if not isinstance(grid, QGridLayout):
        return page
    cloud = load_cloud_settings()
    row = grid.rowCount()

    heading = QLabel("OpenAI / ChatGPT")
    heading.setObjectName("Section")
    grid.addWidget(heading, row, 0, 1, 3); row += 1
    note = QLabel("ChatGPT/OpenAI is the default script writer. OpenAI Images is also available as a scene-image source. API billing is separate from the ChatGPT app subscription.")
    note.setObjectName("Hint"); note.setWordWrap(True)
    grid.addWidget(note, row, 0, 1, 3); row += 1

    login = ui.SoftButton("Login to OpenAI")
    login.clicked.connect(lambda checked=False: QDesktopServices.openUrl(QUrl("https://platform.openai.com/")))
    keys = ui.SoftButton("Open API Keys")
    keys.clicked.connect(lambda checked=False: QDesktopServices.openUrl(QUrl("https://platform.openai.com/api-keys")))
    actions = QHBoxLayout(); actions.addWidget(login); actions.addWidget(keys); actions.addStretch(1)
    grid.addLayout(actions, row, 0, 1, 3); row += 1

    grid.addWidget(QLabel("OpenAI API key"), row, 0)
    self.openai_key_edit = QLineEdit(); self.openai_key_edit.setEchoMode(QLineEdit.Password)
    self.openai_key_edit.setPlaceholderText("Connected securely" if get_secret(OPENAI_SECRET) else "sk-...")
    grid.addWidget(self.openai_key_edit, row, 1)
    connect = ui.SoftButton("Connect"); connect.clicked.connect(lambda checked=False: _connect_openai(self))
    grid.addWidget(connect, row, 2); row += 1
    self.openai_status = QLabel("Connected" if get_secret(OPENAI_SECRET) else "Not connected")
    self.openai_status.setObjectName("Hint")
    grid.addWidget(self.openai_status, row, 1)
    disconnect = ui.SoftButton("Disconnect"); disconnect.clicked.connect(lambda checked=False: _disconnect_openai(self))
    grid.addWidget(disconnect, row, 2); row += 1

    grid.addWidget(QLabel("ChatGPT/OpenAI model"), row, 0)
    self.openai_model_edit = QLineEdit(cloud.openai_text_model)
    grid.addWidget(self.openai_model_edit, row, 1, 1, 2); row += 1
    grid.addWidget(QLabel("OpenAI image model"), row, 0)
    self.openai_image_model_edit = QLineEdit(cloud.openai_image_model)
    grid.addWidget(self.openai_image_model_edit, row, 1, 1, 2); row += 1
    grid.addWidget(QLabel("OpenAI image quality"), row, 0)
    self.openai_image_quality_box = QComboBox(); self.openai_image_quality_box.addItems(["low", "medium", "high", "auto"])
    self.openai_image_quality_box.setCurrentText(cloud.openai_image_quality if cloud.openai_image_quality in {"low", "medium", "high", "auto"} else "medium")
    grid.addWidget(self.openai_image_quality_box, row, 1); row += 1

    eleven_heading = QLabel("ElevenLabs")
    eleven_heading.setObjectName("Section")
    grid.addWidget(eleven_heading, row, 0, 1, 3); row += 1
    eleven_note = QLabel("Use a free ElevenLabs account for cloud narration. Eleven v4 gets a ChatGPT-generated performance script with native tags such as [gasps], [whispers], [sighs], and [curious].")
    eleven_note.setObjectName("Hint"); eleven_note.setWordWrap(True)
    grid.addWidget(eleven_note, row, 0, 1, 3); row += 1

    login11 = ui.SoftButton("Login to ElevenLabs")
    login11.clicked.connect(lambda checked=False: QDesktopServices.openUrl(QUrl("https://elevenlabs.io/app/sign-in")))
    keys11 = ui.SoftButton("Open API Keys")
    keys11.clicked.connect(lambda checked=False: QDesktopServices.openUrl(QUrl("https://elevenlabs.io/app/settings/api-keys")))
    a11 = QHBoxLayout(); a11.addWidget(login11); a11.addWidget(keys11); a11.addStretch(1)
    grid.addLayout(a11, row, 0, 1, 3); row += 1

    grid.addWidget(QLabel("ElevenLabs API key"), row, 0)
    self.eleven_key_edit = QLineEdit(); self.eleven_key_edit.setEchoMode(QLineEdit.Password)
    self.eleven_key_edit.setPlaceholderText("Connected securely" if get_secret(ELEVEN_SECRET) else "xi-api-key")
    grid.addWidget(self.eleven_key_edit, row, 1)
    connect11 = ui.SoftButton("Connect"); connect11.clicked.connect(lambda checked=False: _connect_eleven(self))
    grid.addWidget(connect11, row, 2); row += 1
    self.eleven_status = QLabel("Connected" if get_secret(ELEVEN_SECRET) else "Not connected")
    self.eleven_status.setObjectName("Hint")
    grid.addWidget(self.eleven_status, row, 1)
    disconnect11 = ui.SoftButton("Disconnect"); disconnect11.clicked.connect(lambda checked=False: _disconnect_eleven(self))
    grid.addWidget(disconnect11, row, 2); row += 1

    grid.addWidget(QLabel("ElevenLabs voice"), row, 0)
    self.eleven_voice_box = QComboBox(); self.eleven_voice_box.addItem(cloud.eleven_voice_name or cloud.eleven_voice_id, cloud.eleven_voice_id)
    grid.addWidget(self.eleven_voice_box, row, 1)
    refresh = ui.SoftButton("Refresh Voices"); refresh.clicked.connect(lambda checked=False: _refresh_eleven_voices(self))
    grid.addWidget(refresh, row, 2); row += 1

    grid.addWidget(QLabel("ElevenLabs model"), row, 0)
    self.eleven_model_box = QComboBox()
    self.eleven_model_box.addItem("Eleven v4 — expressive tags", "eleven_v4")
    self.eleven_model_box.addItem("Eleven v4 Turbo", "eleven_v4_turbo")
    self.eleven_model_box.addItem("Flash v2.5 — credit/latency friendly", "eleven_flash_v2_5")
    idx = self.eleven_model_box.findData(cloud.eleven_model_id)
    self.eleven_model_box.setCurrentIndex(idx if idx >= 0 else 0)
    grid.addWidget(self.eleven_model_box, row, 1, 1, 2)
    if get_secret(ELEVEN_SECRET):
        try:
            _refresh_eleven_voices(self)
        except Exception:
            pass
    return page


def save_settings_v110(self):
    result = _PREVIOUS_SAVE_SETTINGS(self)
    if hasattr(self, "openai_model_edit"):
        cloud = load_cloud_settings()
        cloud.openai_text_model = self.openai_model_edit.text().strip() or "gpt-5-mini"
        cloud.openai_image_model = self.openai_image_model_edit.text().strip() or "gpt-image-1"
        cloud.openai_image_quality = self.openai_image_quality_box.currentText()
        if self.eleven_voice_box.count():
            cloud.eleven_voice_name = self.eleven_voice_box.currentText().strip()
            cloud.eleven_voice_id = str(self.eleven_voice_box.currentData() or "").strip() or cloud.eleven_voice_id
        cloud.eleven_model_id = str(self.eleven_model_box.currentData() or "eleven_v4")
        save_cloud_settings(cloud)
    return result


def options_v110(self):
    opts = _PREVIOUS_OPTIONS(self)
    opts.script_mode = self.script_mode_box.currentText() if hasattr(self, "script_mode_box") else "ChatGPT Script"
    if getattr(opts, "voice_engine", "") == ELEVEN_ENGINE:
        opts.runtime_lock = False
    return opts


def generate_v110(self):
    mode = self.script_mode_box.currentText() if hasattr(self, "script_mode_box") else "ChatGPT Script"
    custom = self.custom_script_editor.toPlainText().strip() if hasattr(self, "custom_script_editor") else ""
    if mode == "Custom Script" and not custom:
        QMessageBox.information(self, "ZeroReels", "Paste your narration in Custom Script first.")
        return None
    if mode == "ChatGPT Script" and not get_secret(OPENAI_SECRET):
        QMessageBox.information(self, "ZeroReels", "Connect OpenAI under Settings first. ChatGPT is now the default script writer.")
        self._navigate(4)
        return None
    if hasattr(self, "voice_engine_box") and self.voice_engine_box.currentText() == ELEVEN_ENGINE and not get_secret(ELEVEN_SECRET):
        QMessageBox.information(self, "ZeroReels", "Connect ElevenLabs under Settings first.")
        self._navigate(4)
        return None
    if hasattr(self, "image_source_box") and self.image_source_box.currentText() == "OpenAI Images" and not get_secret(OPENAI_SECRET):
        QMessageBox.information(self, "ZeroReels", "Connect OpenAI under Settings first to use OpenAI Images.")
        self._navigate(4)
        return None
    result = _PREVIOUS_GENERATE(self)
    worker = getattr(self, "worker", None)
    if worker is not None:
        worker.project.script_mode = mode
        worker.project.custom_script = custom
    if worker and worker.isRunning() and hasattr(self, "_append_create_log"):
        source = getattr(self, "image_source_box", None)
        voice = getattr(self, "voice_engine_box", None)
        self._append_create_log(
            f"v0.11 Cloud: {mode} • visuals {source.currentText() if source else 'default'} • voice {voice.currentText() if voice else 'default'}"
        )
    return result


def install() -> None:
    global _PREVIOUS_PIPELINE_RUN, _PREVIOUS_VOICE_RESOLVER, _PREVIOUS_DIAGNOSTICS
    global _PREVIOUS_CREATE_PAGE, _PREVIOUS_SETUP_PAGE, _PREVIOUS_SETTINGS_PAGE, _PREVIOUS_SAVE_SETTINGS
    global _PREVIOUS_OPTIONS, _PREVIOUS_GENERATE, _PREVIOUS_SIDEBAR

    _PREVIOUS_PIPELINE_RUN = pipeline.Pipeline.run
    _PREVIOUS_VOICE_RESOLVER = v071_pipeline.voice_service_for
    _PREVIOUS_DIAGNOSTICS = services.diagnostics
    _PREVIOUS_CREATE_PAGE = ui.MainWindow._create_page
    _PREVIOUS_SETUP_PAGE = ui.MainWindow._setup_page
    _PREVIOUS_SETTINGS_PAGE = ui.MainWindow._settings_page
    _PREVIOUS_SAVE_SETTINGS = ui.MainWindow._save_settings
    _PREVIOUS_OPTIONS = ui.MainWindow._options
    _PREVIOUS_GENERATE = ui.MainWindow._generate
    _PREVIOUS_SIDEBAR = ui.MainWindow._sidebar

    services.ScriptService.generate = chatgpt_generate
    services.diagnostics = cloud_diagnostics
    v071_pipeline._preflight_for_options = cloud_preflight
    v071_pipeline.rewrite_for_measured_duration_v2 = openai_runtime_rewrite
    v070_voice.voice_service_for = cloud_voice_service_for
    v070_pipeline.voice_service_for = cloud_voice_service_for
    v071_pipeline.voice_service_for = cloud_voice_service_for
    pipeline.Pipeline.run = cloud_pipeline_run

    ui.MainWindow._sidebar = sidebar_v110
    ui.MainWindow._create_page = create_page_v110
    ui.MainWindow._setup_page = setup_page_v110
    ui.MainWindow._settings_page = settings_page_v110
    ui.MainWindow._save_settings = save_settings_v110
    ui.MainWindow._options = options_v110
    ui.MainWindow._generate = generate_v110
