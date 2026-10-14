# ZeroReels v0.3 Manual Test Checklist

Use **Mock Mode** for the first pass. This confirms the UI, scene pipeline, voice test track, captions sidecar, and MP4 renderer without requiring Ollama, ComfyUI, Piper, or large models.

## 1. Setup

- Run `setup.bat`.
- Confirm the virtual environment is created and dependencies install without errors.
- Run `run.bat`.
- Confirm the ZeroReels window opens without a console error.

## 2. UI quality

- Sidebar spacing and page alignment are uniform.
- Buttons have subtle hover/press feedback and do not jump or resize.
- Cards have consistent radius, border, and shadow treatment.
- Inputs remain readable at the minimum supported window size.
- Create, Scenes, Queue, Settings, and Diagnostics navigation works.

## 3. Mock generation

Recommended quick values:

- Topic: `A mysterious lighthouse that suddenly went dark`
- Format: `9:16`
- Style: `Cinematic Documentary`
- Length: `15 sec`
- Scenes: `3`
- Mock Mode: ON
- Captions: ON
- Subtle image motion: ON

Click **Generate Video**.

Expected:

- Progress advances through script, images, voice-over, captions, and rendering.
- No paid API or external AI service is contacted.
- A project folder is created under `%USERPROFILE%\.zeroreels\projects`.
- The project folder contains `project.json`, scene images, `narration.wav`, `captions.srt`, and `final.mp4`.
- **Open Output** launches the rendered MP4.
- The Scenes page shows generated preview images, narration, prompts, and durations.

## 4. Queue

- Enter a topic and click **Add to Queue**.
- Open Queue and verify the topic appears.
- Click **Load Next** and verify it returns to Create with that topic loaded.
- **Clear Queue** removes staged items.

## 5. Settings and diagnostics

- Change a harmless field in Settings and click **Save Settings**.
- Restart ZeroReels and verify the value persists.
- Open Diagnostics.
- Installed tools should display as available; missing optional tools should display as unavailable without crashing the app.
- The bundled FFmpeg fallback should be detected after normal setup.

## 6. Real local AI test — after Mock Mode passes

Configure tools one at a time instead of all at once:

1. Ollama + selected local language model.
2. ComfyUI + exported API workflow JSON using ZeroReels placeholders.
3. Piper executable + voice model.
4. FFmpeg if you prefer a system installation over the bundled fallback.

Then disable Mock Mode and run a 15-second / 3-scene project first.

## Report useful failures

When something fails, capture:

- Which pipeline stage was shown in the status area.
- The exact error message.
- Whether Mock Mode was enabled.
- Selected format/style/scene count.
- GPU model and VRAM when the failure involves ComfyUI.

Do not upload private model files, generated media, or personal settings unless they are needed to reproduce the issue.
