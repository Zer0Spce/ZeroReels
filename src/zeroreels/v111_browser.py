from __future__ import annotations

from dataclasses import replace
from pathlib import Path

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QComboBox, QGridLayout, QHBoxLayout, QLabel, QMessageBox, QPlainTextEdit, QVBoxLayout

from . import pipeline, services, ui, v070_pipeline, v070_voice, v071_pipeline
from .browser_ai import (
    CHATGPT_IMAGE_SOURCE,
    ELEVEN_BROWSER_ENGINE,
    ChatGPTImageService,
    ElevenLabsBrowserVoiceService,
    browser_runtime_rewrite,
    chatgpt_browser_generate,
    close_thread_clients,
)
from .browser_sessions import (
    all_statuses,
    find_chrome_executable,
    launch_login_browser,
    open_service_browser,
    profile_path,
    reset_profile,
    service_status,
    test_session,
)


_PREVIOUS_RUN = None
_PREVIOUS_VOICE_RESOLVER = None
_PREVIOUS_DIAGNOSTICS = None
_PREVIOUS_CREATE_PAGE = None
_PREVIOUS_SETUP_PAGE = None
_PREVIOUS_SETTINGS_PAGE = None
_PREVIOUS_OPTIONS = None
_PREVIOUS_MAKE_PROJECT = None
_PREVIOUS_GENERATE = None
_PREVIOUS_SIDEBAR = None
_PREVIOUS_SETUP_COMPLETE = None
_CHATGPT_IMAGE_ACTIVE = False


def _profile_ready(service_id: str) -> bool:
    return bool(service_status(service_id).get("saved"))


def browser_preflight(self, options) -> None:
    missing: list[str] = []
    script_mode = getattr(options, "script_mode", "ChatGPT Browser")
    needs_chatgpt = script_mode != "Custom Script" or _CHATGPT_IMAGE_ACTIVE
    engine = getattr(options, "voice_engine", "Kokoro Directed")
    needs_eleven = engine == ELEVEN_BROWSER_ENGINE

    if (needs_chatgpt or needs_eleven) and not find_chrome_executable():
        missing.append("Google Chrome")
    if needs_chatgpt and not _profile_ready("chatgpt"):
        missing.append("ChatGPT Chrome profile (Settings → Browser Accounts → Login Chrome)")
    if needs_eleven and not _profile_ready("elevenlabs"):
        missing.append("ElevenLabs Chrome profile (Settings → Browser Accounts → Login Chrome)")

    mode = getattr(options, "image_source_mode", "AI Generated")
    if not _CHATGPT_IMAGE_ACTIVE and mode != "Real Web Images":
        try:
            services.ComfyImageService(self.settings).validate_server()
        except Exception:
            missing.append("ComfyUI / FLUX (or choose ChatGPT Images)")

    if engine in {"Kokoro Directed", "Kokoro Classic"}:
        model = Path(self.settings.kokoro_model_path).expanduser()
        voices = Path(self.settings.kokoro_voices_path).expanduser()
        if not model.exists() or not voices.exists():
            missing.append("Kokoro voice files")

    try:
        from .browser_ai import _ffmpeg
        _ffmpeg(self.settings)
    except Exception:
        missing.append("FFmpeg")

    if missing:
        raise RuntimeError("Generation is not ready yet. Complete:\n• " + "\n• ".join(missing))


def browser_diagnostics(settings):
    rows = [row for row in _PREVIOUS_DIAGNOSTICS(settings) if row[0] not in {"Ollama", "Script model"}]
    chrome = find_chrome_executable()
    statuses = all_statuses()
    chat = statuses["chatgpt"]
    eleven = statuses["elevenlabs"]
    rows.insert(0, ("Google Chrome", bool(chrome), chrome or "not found"))
    rows.insert(1, ("ChatGPT Browser Profile", chat["status"] == "verified", f"{chat['status']} • {chat['profile']}"))
    rows.insert(2, ("ElevenLabs Browser Profile", eleven["status"] == "verified", f"{eleven['status']} • {eleven['profile']}"))
    return rows


def browser_voice_service_for(settings, engine: str, delivery: str, mock_mode: bool = False):
    if mock_mode:
        return services.MockVoiceService()
    if engine == ELEVEN_BROWSER_ENGINE:
        return ElevenLabsBrowserVoiceService(settings, delivery)
    return _PREVIOUS_VOICE_RESOLVER(settings, engine, delivery, mock_mode)


def browser_pipeline_run(self, project, options, progress=lambda value, text: None):
    global _CHATGPT_IMAGE_ACTIVE
    use_chatgpt_images = (
        not bool(getattr(options, "mock_mode", False))
        and getattr(options, "image_source_mode", "") == CHATGPT_IMAGE_SOURCE
    )
    old_image_service = services.ComfyImageService
    _CHATGPT_IMAGE_ACTIVE = use_chatgpt_images
    try:
        if use_chatgpt_images:
            services.ComfyImageService = ChatGPTImageService
            # Feed the existing v0.10 AI-image/video-B-roll router its AI-shaped mode.
            routed = replace(options, image_source_mode="AI Generated")
            result = _PREVIOUS_RUN(self, project, routed, progress)
            result.image_source_mode = CHATGPT_IMAGE_SOURCE
            if result.output_dir:
                result.save(Path(result.output_dir) / "project.json")
            return result
        return _PREVIOUS_RUN(self, project, options, progress)
    finally:
        services.ComfyImageService = old_image_service
        _CHATGPT_IMAGE_ACTIVE = False
        close_thread_clients()


def sidebar_v111(self):
    frame = _PREVIOUS_SIDEBAR(self)
    for label in frame.findChildren(QLabel):
        if label.text().startswith("v0."):
            label.setText("v0.11.1 BROWSER")
            label.setMaximumWidth(152)
            break
    return frame


def create_page_v111(self):
    page = _PREVIOUS_CREATE_PAGE(self)
    scroll = getattr(self, "create_scroll_area", None)
    body = scroll.widget().layout() if scroll is not None and scroll.widget() is not None else None
    if isinstance(body, QVBoxLayout):
        card = ui.Card()
        grid = QGridLayout(card)
        grid.setContentsMargins(20, 18, 20, 18)
        grid.setHorizontalSpacing(14)
        grid.setVerticalSpacing(9)
        title = QLabel("ChatGPT Browser Script")
        title.setObjectName("Section")
        note = QLabel(
            "Uses the normal free ChatGPT website through ZeroReels' saved Chrome profile. No OpenAI API key and no Story Director."
        )
        note.setObjectName("Hint")
        note.setWordWrap(True)
        grid.addWidget(title, 0, 0, 1, 2)
        grid.addWidget(note, 1, 0, 1, 2)
        grid.addWidget(QLabel("Script source"), 2, 0)
        self.script_mode_box = QComboBox()
        self.script_mode_box.addItems(["ChatGPT Browser", "Custom Script"])
        grid.addWidget(self.script_mode_box, 3, 0, 1, 2)
        self.custom_script_editor = QPlainTextEdit()
        self.custom_script_editor.setPlaceholderText("Switch to Custom Script to paste finished narration.")
        self.custom_script_editor.setMinimumHeight(92)
        self.custom_script_editor.setMaximumHeight(165)
        self.custom_script_editor.setEnabled(False)
        self.script_mode_box.currentTextChanged.connect(
            lambda value: self.custom_script_editor.setEnabled(value == "Custom Script")
        )
        grid.addWidget(self.custom_script_editor, 4, 0, 1, 2)
        body.insertWidget(1, card)

    if hasattr(self, "image_source_box"):
        items = [self.image_source_box.itemText(i) for i in range(self.image_source_box.count())]
        if CHATGPT_IMAGE_SOURCE not in items:
            self.image_source_box.insertItem(0, CHATGPT_IMAGE_SOURCE)
        saved = getattr(self.settings, "image_source_mode", "AI Generated")
        if saved == "OpenAI Images":
            saved = CHATGPT_IMAGE_SOURCE
        if saved in [self.image_source_box.itemText(i) for i in range(self.image_source_box.count())]:
            self.image_source_box.setCurrentText(saved)
        self.image_source_box.setToolTip(
            "ChatGPT Images uses the free ChatGPT website in ZeroReels' saved Chrome profile. Local AI uses FLUX; Real/Hybrid uses Wikimedia media."
        )

    if hasattr(self, "voice_engine_box"):
        items = [self.voice_engine_box.itemText(i) for i in range(self.voice_engine_box.count())]
        if ELEVEN_BROWSER_ENGINE not in items:
            self.voice_engine_box.insertItem(0, ELEVEN_BROWSER_ENGINE)
        if getattr(self.settings, "voice_engine", "") in {ELEVEN_BROWSER_ENGINE, "ElevenLabs Cloud"}:
            self.voice_engine_box.setCurrentText(ELEVEN_BROWSER_ENGINE)

        def voice_changed(value: str):
            if hasattr(self, "runtime_lock_check"):
                is_eleven = value == ELEVEN_BROWSER_ENGINE
                self.runtime_lock_check.setEnabled(not is_eleven)
                if is_eleven:
                    self.runtime_lock_check.setChecked(False)
                    self.runtime_lock_check.setToolTip(
                        "Disabled for ElevenLabs Browser to avoid consuming the free account quota twice."
                    )
        self.voice_engine_box.currentTextChanged.connect(voice_changed)
        voice_changed(self.voice_engine_box.currentText())
    return page


def setup_page_v111(self):
    page = _PREVIOUS_SETUP_PAGE(self)
    for label in page.findChildren(QLabel):
        if label.text() == "Script AI":
            label.setText("Browser AI")
            card = label.parentWidget()
            if card and card.layout():
                for child in card.findChildren(QLabel):
                    if "Ollama" in child.text() or "Qwen" in child.text():
                        child.setText(
                            "ChatGPT and ElevenLabs run through ZeroReels-owned Chrome profiles. Login once in Settings, then ZeroReels reuses those sessions automatically."
                        )
                for button in card.findChildren(ui.SoftButton):
                    if "Ollama" in button.text() or "Script Model" in button.text() or "Quality Writer" in button.text():
                        button.hide()
                open_accounts = ui.SoftButton("Open Browser Accounts")
                open_accounts.setObjectName("Primary")
                open_accounts.clicked.connect(lambda checked=False: self._navigate(4))
                card.layout().addWidget(open_accounts)
        elif label.text() == "Image AI":
            label.setText("Local Image AI (Optional)")
        elif label.text() == "Voice":
            label.setText("Local Voice (Optional)")
    for label in page.findChildren(QLabel):
        if "Open Ollama" in label.text():
            label.setText("Login to ChatGPT and ElevenLabs in Browser Accounts. ComfyUI and Kokoro are optional local alternatives.")
    return page


def _status_text(service_id: str) -> str:
    status = service_status(service_id)
    return f"{status['status']} • {status['message']}"


def _refresh_browser_labels(self):
    if hasattr(self, "chatgpt_browser_status"):
        self.chatgpt_browser_status.setText(_status_text("chatgpt"))
    if hasattr(self, "eleven_browser_status"):
        self.eleven_browser_status.setText(_status_text("elevenlabs"))
    if hasattr(self, "chrome_browser_status"):
        self.chrome_browser_status.setText(find_chrome_executable() or "Google Chrome not found")


def _login(self, service_id: str):
    try:
        launch_login_browser(service_id)
        _refresh_browser_labels(self)
        QMessageBox.information(
            self,
            "ZeroReels Browser Login",
            "A normal Chrome window opened with ZeroReels' dedicated profile. Finish login/2FA/CAPTCHA there. Then return to ZeroReels and click Test Session.",
        )
    except Exception as exc:
        QMessageBox.critical(self, "Browser Login", str(exc))


def _test(self, service_id: str):
    name = "ChatGPT" if service_id == "chatgpt" else "ElevenLabs"

    def action(progress):
        progress(10, f"Opening {name} saved Chrome profile")
        result = test_session(service_id)
        progress(100, result["message"])
        if not result["ok"]:
            raise RuntimeError(result["message"])

    self._browser_refresh_after_setup = True
    self._run_setup(f"{name} browser session verified", action)


def _open(self, service_id: str):
    try:
        open_service_browser(service_id)
        _refresh_browser_labels(self)
    except Exception as exc:
        QMessageBox.critical(self, "Open Browser", str(exc))


def _reset(self, service_id: str):
    name = "ChatGPT" if service_id == "chatgpt" else "ElevenLabs"
    answer = QMessageBox.question(
        self,
        f"Reset {name} Profile",
        f"Delete ZeroReels' saved {name} Chrome profile and sign out of that ZeroReels profile?",
        QMessageBox.Yes | QMessageBox.No,
        QMessageBox.No,
    )
    if answer == QMessageBox.Yes:
        reset_profile(service_id)
        _refresh_browser_labels(self)


def settings_page_v111(self):
    page = _PREVIOUS_SETTINGS_PAGE(self)
    cards = page.findChildren(ui.Card)
    if not cards:
        return page
    grid = cards[0].layout()
    if not isinstance(grid, QGridLayout):
        return page

    # Legacy local script settings remain load-compatible but are no longer part of the UI.
    for label in page.findChildren(QLabel):
        if label.text() in {"Ollama URL", "Ollama model"}:
            label.hide()
    for key in ("ollama_url", "ollama_model"):
        edit = getattr(self, "setting_edits", {}).get(key)
        if edit is not None:
            edit.hide()

    row = grid.rowCount()
    heading = QLabel("Browser Accounts")
    heading.setObjectName("Section")
    grid.addWidget(heading, row, 0, 1, 3); row += 1
    note = QLabel(
        "ZeroReels uses its own persistent Chrome profiles for ChatGPT and ElevenLabs, like ZeroPOD. No API keys. Login happens in normal Chrome; automation reuses the saved session afterwards."
    )
    note.setObjectName("Hint"); note.setWordWrap(True)
    grid.addWidget(note, row, 0, 1, 3); row += 1

    grid.addWidget(QLabel("Google Chrome"), row, 0)
    self.chrome_browser_status = QLabel(find_chrome_executable() or "Google Chrome not found")
    self.chrome_browser_status.setObjectName("Hint")
    grid.addWidget(self.chrome_browser_status, row, 1, 1, 2); row += 1

    def add_service(service_id: str, title: str):
        nonlocal row
        grid.addWidget(QLabel(title), row, 0)
        status = QLabel(_status_text(service_id)); status.setObjectName("Hint"); status.setWordWrap(True)
        if service_id == "chatgpt":
            self.chatgpt_browser_status = status
        else:
            self.eleven_browser_status = status
        grid.addWidget(status, row, 1, 1, 2); row += 1
        actions = QHBoxLayout()
        login = ui.SoftButton("Login Chrome")
        login.clicked.connect(lambda checked=False, sid=service_id: _login(self, sid))
        test = ui.SoftButton("Test Session")
        test.setObjectName("SecondaryAccent")
        test.clicked.connect(lambda checked=False, sid=service_id: _test(self, sid))
        open_btn = ui.SoftButton("Open")
        open_btn.clicked.connect(lambda checked=False, sid=service_id: _open(self, sid))
        reset = ui.SoftButton("Reset Profile")
        reset.clicked.connect(lambda checked=False, sid=service_id: _reset(self, sid))
        actions.addWidget(login); actions.addWidget(test); actions.addWidget(open_btn); actions.addWidget(reset); actions.addStretch(1)
        grid.addLayout(actions, row, 1, 1, 2); row += 1
        path_label = QLabel(str(profile_path(service_id))); path_label.setObjectName("Hint"); path_label.setWordWrap(True)
        grid.addWidget(path_label, row, 1, 1, 2); row += 1

    add_service("chatgpt", "ChatGPT profile")
    add_service("elevenlabs", "ElevenLabs profile")
    return page


def options_v111(self):
    opts = _PREVIOUS_OPTIONS(self)
    opts.script_mode = self.script_mode_box.currentText() if hasattr(self, "script_mode_box") else "ChatGPT Browser"
    if getattr(opts, "voice_engine", "") == ELEVEN_BROWSER_ENGINE:
        opts.runtime_lock = False
    return opts


def make_project_v111(self):
    mode = self.script_mode_box.currentText() if hasattr(self, "script_mode_box") else "ChatGPT Browser"
    custom = self.custom_script_editor.toPlainText().strip() if hasattr(self, "custom_script_editor") else ""
    if mode == "Custom Script" and not custom:
        raise ValueError("Paste your narration in Custom Script first.")
    restore = None
    if mode == "Custom Script" and custom and not self.topic.toPlainText().strip():
        restore = ""
        self.topic.setPlainText(" ".join(custom.split()[:12]).strip(" .,!?:;-") or "Custom narration")
    try:
        project = _PREVIOUS_MAKE_PROJECT(self)
    finally:
        if restore is not None:
            self.topic.setPlainText(restore)
    project.script_mode = mode
    project.custom_script = custom
    project.script_model_mode = "ChatGPT Browser"
    return project


def generate_v111(self):
    mode = self.script_mode_box.currentText() if hasattr(self, "script_mode_box") else "ChatGPT Browser"
    if mode != "Custom Script" and not _profile_ready("chatgpt"):
        QMessageBox.information(self, "ZeroReels", "Login to ChatGPT under Settings → Browser Accounts first.")
        self._navigate(4)
        return None
    if hasattr(self, "image_source_box") and self.image_source_box.currentText() == CHATGPT_IMAGE_SOURCE and not _profile_ready("chatgpt"):
        QMessageBox.information(self, "ZeroReels", "Login to ChatGPT under Settings → Browser Accounts first.")
        self._navigate(4)
        return None
    if hasattr(self, "voice_engine_box") and self.voice_engine_box.currentText() == ELEVEN_BROWSER_ENGINE and not _profile_ready("elevenlabs"):
        QMessageBox.information(self, "ZeroReels", "Login to ElevenLabs under Settings → Browser Accounts first.")
        self._navigate(4)
        return None
    result = _PREVIOUS_GENERATE(self)
    worker = getattr(self, "worker", None)
    if worker and worker.isRunning() and hasattr(self, "_append_create_log"):
        source = getattr(self, "image_source_box", None)
        voice = getattr(self, "voice_engine_box", None)
        self._append_create_log(
            f"Browser workflow: {mode} • visuals {source.currentText() if source else 'default'} • voice {voice.currentText() if voice else 'default'}"
        )
    return result


def setup_complete_v111(self, label: str):
    result = _PREVIOUS_SETUP_COMPLETE(self, label)
    if getattr(self, "_browser_refresh_after_setup", False):
        self._browser_refresh_after_setup = False
        _refresh_browser_labels(self)
    return result


def install() -> None:
    global _PREVIOUS_RUN, _PREVIOUS_VOICE_RESOLVER, _PREVIOUS_DIAGNOSTICS
    global _PREVIOUS_CREATE_PAGE, _PREVIOUS_SETUP_PAGE, _PREVIOUS_SETTINGS_PAGE
    global _PREVIOUS_OPTIONS, _PREVIOUS_MAKE_PROJECT, _PREVIOUS_GENERATE, _PREVIOUS_SIDEBAR, _PREVIOUS_SETUP_COMPLETE

    _PREVIOUS_RUN = pipeline.Pipeline.run
    _PREVIOUS_VOICE_RESOLVER = v071_pipeline.voice_service_for
    _PREVIOUS_DIAGNOSTICS = services.diagnostics
    _PREVIOUS_CREATE_PAGE = ui.MainWindow._create_page
    _PREVIOUS_SETUP_PAGE = ui.MainWindow._setup_page
    _PREVIOUS_SETTINGS_PAGE = ui.MainWindow._settings_page
    _PREVIOUS_OPTIONS = ui.MainWindow._options
    _PREVIOUS_MAKE_PROJECT = ui.MainWindow._make_project
    _PREVIOUS_GENERATE = ui.MainWindow._generate
    _PREVIOUS_SIDEBAR = ui.MainWindow._sidebar
    _PREVIOUS_SETUP_COMPLETE = ui.MainWindow._setup_complete

    services.ScriptService.generate = chatgpt_browser_generate
    services.diagnostics = browser_diagnostics
    ui.diagnostics = browser_diagnostics
    v071_pipeline._preflight_for_options = browser_preflight
    v071_pipeline.rewrite_for_measured_duration_v2 = browser_runtime_rewrite
    v070_voice.voice_service_for = browser_voice_service_for
    v070_pipeline.voice_service_for = browser_voice_service_for
    v071_pipeline.voice_service_for = browser_voice_service_for
    pipeline.Pipeline.run = browser_pipeline_run

    ui.MainWindow._sidebar = sidebar_v111
    ui.MainWindow._create_page = create_page_v111
    ui.MainWindow._setup_page = setup_page_v111
    ui.MainWindow._settings_page = settings_page_v111
    ui.MainWindow._options = options_v111
    ui.MainWindow._make_project = make_project_v111
    ui.MainWindow._generate = generate_v111
    ui.MainWindow._setup_complete = setup_complete_v111
