from __future__ import annotations

from dataclasses import dataclass, asdict
from pathlib import Path
import base64
import json
import os
import re
import urllib.error
import urllib.request

from PySide6.QtWidgets import QLabel, QLineEdit

from . import services, ui, v070_pipeline, v070_voice, v071_pipeline, v082_natural_voice
from .config import APP_DIR


DRAMA3_ENGINE = "Fish Audio Drama 3 (Server)"
DRAMA3_SETTINGS_FILE = APP_DIR / "drama3.json"
DRAMA3_DEFAULT_ENDPOINT = "http://127.0.0.1:8000"
DRAMA3_DEFAULT_MODEL = "fishaudio/drama-3"


@dataclass(slots=True)
class Drama3Settings:
    endpoint: str = DRAMA3_DEFAULT_ENDPOINT
    model: str = DRAMA3_DEFAULT_MODEL
    api_key: str = ""


def load_drama3_settings() -> Drama3Settings:
    if not DRAMA3_SETTINGS_FILE.exists():
        return Drama3Settings()
    try:
        data = json.loads(DRAMA3_SETTINGS_FILE.read_text(encoding="utf-8"))
        return Drama3Settings(
            endpoint=str(data.get("endpoint") or DRAMA3_DEFAULT_ENDPOINT).strip(),
            model=str(data.get("model") or DRAMA3_DEFAULT_MODEL).strip(),
            api_key=str(data.get("api_key") or "").strip(),
        )
    except Exception:
        return Drama3Settings()


def save_drama3_settings(settings: Drama3Settings) -> None:
    APP_DIR.mkdir(parents=True, exist_ok=True)
    DRAMA3_SETTINGS_FILE.write_text(json.dumps(asdict(settings), indent=2), encoding="utf-8")


def _speech_url(endpoint: str) -> str:
    value = (endpoint or DRAMA3_DEFAULT_ENDPOINT).strip().rstrip("/")
    if value.endswith("/v1/audio/speech"):
        return value
    if value.endswith("/v1"):
        return value + "/audio/speech"
    return value + "/v1/audio/speech"


def _models_url(endpoint: str) -> str:
    value = (endpoint or DRAMA3_DEFAULT_ENDPOINT).strip().rstrip("/")
    if value.endswith("/v1/audio/speech"):
        value = value[: -len("/v1/audio/speech")]
    elif value.endswith("/v1"):
        value = value[: -len("/v1")]
    return value.rstrip("/") + "/v1/models"


def _headers(config: Drama3Settings) -> dict[str, str]:
    headers = {
        "Content-Type": "application/json",
        "Accept": "audio/wav, application/json",
        "User-Agent": "ZeroReels/0.8.3",
    }
    key = (config.api_key or os.environ.get("ZEROREELS_DRAMA3_API_KEY", "")).strip()
    if key:
        headers["Authorization"] = f"Bearer {key}"
    return headers


def _reference_data_uri(path: Path) -> str:
    suffix = path.suffix.lower()
    mime = {
        ".wav": "audio/wav",
        ".mp3": "audio/mpeg",
        ".flac": "audio/flac",
        ".ogg": "audio/ogg",
        ".m4a": "audio/mp4",
    }.get(suffix, "application/octet-stream")
    encoded = base64.b64encode(path.read_bytes()).decode("ascii")
    return f"data:{mime};base64,{encoded}"


def _spoken_chunks(text: str, max_chars: int = 430) -> list[str]:
    """Keep Drama 3 requests comfortably below long-form endpoint limits."""
    clean = " ".join((text or "").split()).strip()
    if not clean:
        return []
    sentences = [s.strip() for s in re.split(r"(?<=[.!?…])\s+", clean) if s.strip()]
    if not sentences:
        return [clean]
    chunks: list[str] = []
    current = ""
    for sentence in sentences:
        proposed = (current + " " + sentence).strip()
        if current and len(proposed) > max_chars:
            chunks.append(current)
            current = sentence
        else:
            current = proposed
    if current:
        chunks.append(current)
    return chunks


def _decode_audio_response(response) -> bytes:
    raw = response.read()
    content_type = ""
    try:
        content_type = str(response.headers.get("Content-Type", "")).lower()
    except Exception:
        pass
    if "json" not in content_type and raw.startswith(b"RIFF"):
        return raw
    if "json" in content_type or raw.lstrip().startswith(b"{"):
        data = json.loads(raw.decode("utf-8", errors="replace"))
        encoded = str(data.get("audio_b64") or data.get("audio") or "")
        if encoded.startswith("data:") and "," in encoded:
            encoded = encoded.split(",", 1)[1]
        if encoded:
            return base64.b64decode(encoded)
        message = data.get("error") or data.get("detail") or data.get("message") or "Drama 3 server returned JSON without audio"
        raise RuntimeError(str(message))
    return raw


def _drama3_request(config: Drama3Settings, text: str, ref_uri: str, ref_text: str, timeout: int = 1800) -> bytes:
    payload = {
        "model": config.model or DRAMA3_DEFAULT_MODEL,
        "input": text,
        "voice": "default",
        "ref_audio": ref_uri,
        "ref_text": ref_text,
        "response_format": "wav",
        "temperature": 0.9,
        "top_p": 0.9,
    }
    request = urllib.request.Request(
        _speech_url(config.endpoint),
        data=json.dumps(payload).encode("utf-8"),
        headers=_headers(config),
        method="POST",
    )
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            return _decode_audio_response(response)
    except urllib.error.HTTPError as exc:
        try:
            detail = exc.read().decode("utf-8", errors="replace")[-1200:]
        except Exception:
            detail = str(exc)
        raise RuntimeError(f"Drama 3 server HTTP {exc.code}: {detail}") from exc
    except urllib.error.URLError as exc:
        raise RuntimeError(f"Drama 3 server is unreachable: {exc.reason}") from exc


def _fallback_voice(service, project, out_dir: Path, progress, detail: str) -> Path:
    short = " ".join((detail or "unknown error").split())[-260:]
    v070_voice._progress(progress, 22, f"Drama 3 unavailable • {short} • using local voice fallback")
    try:
        chatterbox_python = Path(getattr(service.settings, "chatterbox_python", "") or "").expanduser()
        reference = Path(getattr(service.settings, "natural_voice_ref", "") or "").expanduser()
        if chatterbox_python.exists() and reference.exists():
            fallback = v082_natural_voice.FastCloneVoiceService(service.settings, service.delivery)
            result = fallback.generate(project, out_dir, progress=progress)
            project.voice_engine_used = project.voice_engine_used or "Chatterbox Turbo Fast Clone (Drama 3 fallback)"
            return result
    except Exception:
        pass
    fallback = v070_voice.KokoroDirectedVoiceService(service.settings, service.delivery)
    result = fallback.generate(project, out_dir, progress=progress)
    if "fallback" not in (project.voice_engine_used or "").lower():
        project.voice_engine_used = "Kokoro Directed (Drama 3 fallback)"
    return result


class Drama3VoiceService:
    def __init__(self, settings, delivery: str):
        self.settings = settings
        self.delivery = delivery
        self.engine = DRAMA3_ENGINE

    def generate(self, project, out_dir: Path, progress=None) -> Path:
        config = load_drama3_settings()
        ref = Path(getattr(self.settings, "natural_voice_ref", "") or "").expanduser()
        ref_text = (getattr(self.settings, "natural_voice_ref_text", "") or "").strip()
        if not ref.exists():
            return _fallback_voice(self, project, out_dir, progress, "reference voice file is missing")
        if not ref_text:
            return _fallback_voice(self, project, out_dir, progress, "reference transcript is missing in Settings")

        text = v070_voice.directed_script(project, self.delivery)
        chunks = _spoken_chunks(text)
        if not chunks:
            raise RuntimeError("Narration is empty")

        out_dir.mkdir(parents=True, exist_ok=True)
        target = out_dir / "narration.wav"
        try:
            ref_uri = _reference_data_uri(ref)
            parts: list[Path] = []
            v070_voice._progress(progress, 20, f"Drama 3 • voice cloning through {config.model}")
            for index, chunk in enumerate(chunks, start=1):
                pct = min(28, 20 + int(8 * (index - 1) / max(1, len(chunks))))
                if len(chunks) > 1:
                    v070_voice._progress(progress, pct, f"Drama 3 • rendering narration chunk {index}/{len(chunks)}")
                audio = _drama3_request(config, chunk, ref_uri, ref_text)
                if not audio.startswith(b"RIFF"):
                    raise RuntimeError("Drama 3 server did not return a WAV response")
                part = out_dir / f"drama3_{index:02d}.wav"
                part.write_bytes(audio)
                parts.append(part)

            if len(parts) == 1:
                parts[0].replace(target)
            else:
                profile = v070_voice.DELIVERY_PROFILES.get(
                    self.delivery, v070_voice.DELIVERY_PROFILES["Natural Storyteller"]
                )
                services._concat_wavs(parts, target, silence_seconds=max(0.06, min(0.18, float(profile["pause"]) * 0.55)))
                for part in parts:
                    try:
                        part.unlink(missing_ok=True)
                    except OSError:
                        pass

            if not target.exists() or target.stat().st_size < 1000:
                raise RuntimeError("Drama 3 did not produce a valid narration WAV")
            duration = v070_voice._wav_duration(target)
            v070_voice.apply_scene_timing(project, duration, self.delivery)
            project.actual_seconds = round(duration, 2)
            project.voice_engine_used = DRAMA3_ENGINE
            project.voice_delivery = self.delivery
            v070_voice._progress(progress, 29, f"Drama 3 voice ready • {duration:.1f}s • cloned reference voice")
            return target
        except Exception as exc:
            return _fallback_voice(self, project, out_dir, progress, str(exc))


def voice_service_for_v083(settings, engine: str, delivery: str, mock_mode: bool = False):
    original = getattr(voice_service_for_v083, "_original", None)
    if engine == DRAMA3_ENGINE and not mock_mode:
        return Drama3VoiceService(settings, delivery)
    if original is not None:
        return original(settings, engine, delivery, mock_mode)
    return v070_voice.KokoroDirectedVoiceService(settings, delivery)


def test_drama3_server(progress=None, log=None) -> None:
    config = load_drama3_settings()
    if progress:
        progress(15, "Checking Drama 3 server")
    request = urllib.request.Request(_models_url(config.endpoint), headers=_headers(config), method="GET")
    try:
        with urllib.request.urlopen(request, timeout=12) as response:
            raw = response.read().decode("utf-8", errors="replace")
    except Exception as exc:
        raise RuntimeError(
            "Drama 3 server could not be reached. Start a compatible SGLang/vLLM Drama 3 server, "
            "then set its endpoint under Settings → Drama 3. " + str(exc)
        ) from exc
    if log:
        log((raw[:500] or "Server responded successfully").replace("\n", " "))
    if progress:
        progress(100, "Drama 3 server reachable")


def install() -> None:
    # Capture the fully patched v0.8.2 voice resolver so all older local engines keep working.
    voice_service_for_v083._original = v070_voice.voice_service_for
    v070_voice.voice_service_for = voice_service_for_v083
    v070_pipeline.voice_service_for = voice_service_for_v083
    v071_pipeline.voice_service_for = voice_service_for_v083

    original_sidebar = ui.MainWindow._sidebar
    original_create_page = ui.MainWindow._create_page
    original_setup_page = ui.MainWindow._setup_page
    original_settings_page = ui.MainWindow._settings_page
    original_save_settings = ui.MainWindow._save_settings

    def sidebar(self):
        frame = original_sidebar(self)
        for label in frame.findChildren(QLabel):
            if label.text().startswith("v0."):
                label.setText("v0.8.3 DRAMA")
                label.setMaximumWidth(138)
                break
        return frame

    def create_page(self):
        page = original_create_page(self)
        box = getattr(self, "voice_engine_box", None)
        if box is not None:
            items = [box.itemText(i) for i in range(box.count())]
            if DRAMA3_ENGINE not in items:
                box.insertItem(0, DRAMA3_ENGINE)
            if getattr(self.settings, "voice_engine", "") == DRAMA3_ENGINE:
                box.setCurrentText(DRAMA3_ENGINE)
            box.setToolTip(
                "Fish Audio Drama 3 connects to a compatible remote/self-hosted server and clones the reference WAV. "
                "Chatterbox Turbo Fast Clone remains the recommended fully local option on 6 GB GPUs."
            )
        return page

    def settings_page(self):
        page = original_settings_page(self)
        config = load_drama3_settings()
        cards = page.findChildren(ui.Card)
        if not cards:
            return page
        grid = cards[0].layout()
        if grid is None or not hasattr(grid, "addWidget"):
            return page
        row = grid.rowCount()

        heading = QLabel("Fish Audio Drama 3")
        heading.setObjectName("Section")
        grid.addWidget(heading, row, 0, 1, 3)
        row += 1
        note = QLabel(
            "Connect ZeroReels to a Drama 3 OpenAI-compatible speech server. The official full model is ~41.5 GB and currently targets large NVIDIA GPUs; use this server mode instead of trying to load it on a 6 GB laptop GPU."
        )
        note.setObjectName("Hint")
        note.setWordWrap(True)
        grid.addWidget(note, row, 0, 1, 3)
        row += 1

        grid.addWidget(QLabel("Drama 3 server endpoint"), row, 0)
        self.drama3_endpoint_edit = QLineEdit(config.endpoint)
        self.drama3_endpoint_edit.setPlaceholderText(DRAMA3_DEFAULT_ENDPOINT)
        grid.addWidget(self.drama3_endpoint_edit, row, 1, 1, 2)
        row += 1

        grid.addWidget(QLabel("Drama 3 model ID"), row, 0)
        self.drama3_model_edit = QLineEdit(config.model)
        self.drama3_model_edit.setPlaceholderText(DRAMA3_DEFAULT_MODEL)
        grid.addWidget(self.drama3_model_edit, row, 1, 1, 2)
        row += 1

        grid.addWidget(QLabel("Drama 3 API key (optional)"), row, 0)
        self.drama3_key_edit = QLineEdit(config.api_key)
        self.drama3_key_edit.setEchoMode(QLineEdit.Password)
        self.drama3_key_edit.setPlaceholderText("Leave blank for local/LAN server")
        grid.addWidget(self.drama3_key_edit, row, 1, 1, 2)

        for label in page.findChildren(QLabel):
            if label.text() == "Reference transcript (F5-TTS)":
                label.setText("Reference transcript (F5 / Drama 3)")
                break
        return page

    def save_settings(self):
        result = original_save_settings(self)
        if hasattr(self, "drama3_endpoint_edit"):
            save_drama3_settings(
                Drama3Settings(
                    endpoint=self.drama3_endpoint_edit.text().strip() or DRAMA3_DEFAULT_ENDPOINT,
                    model=self.drama3_model_edit.text().strip() or DRAMA3_DEFAULT_MODEL,
                    api_key=self.drama3_key_edit.text().strip(),
                )
            )
            if hasattr(self, "status_detail"):
                self.status_detail.setText("Settings saved locally, including Drama 3 server configuration.")
        return result

    def setup_page(self):
        page = original_setup_page(self)
        for label in page.findChildren(QLabel):
            if label.text() != "Voice":
                continue
            card = label.parentWidget()
            if not card or not card.layout():
                continue
            note = QLabel(
                "Fish Audio Drama 3: multi-speaker, expressive TTS with reference-voice cloning. ZeroReels connects to a compatible server because the official checkpoint is too large for typical laptop GPUs. Fish Audio's license also requires consent/legal rights for any identifiable voice you clone."
            )
            note.setObjectName("Hint")
            note.setWordWrap(True)
            button = ui.SoftButton("Test Drama 3 Server")
            button.clicked.connect(
                lambda checked=False: self._run_setup(
                    "Drama 3 server ready",
                    lambda progress, log: test_drama3_server(progress, log),
                )
            )
            card.layout().addWidget(note)
            card.layout().addWidget(button)
            break
        return page

    ui.MainWindow._sidebar = sidebar
    ui.MainWindow._create_page = create_page
    ui.MainWindow._setup_page = setup_page
    ui.MainWindow._settings_page = settings_page
    ui.MainWindow._save_settings = save_settings
