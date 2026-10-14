# ZeroReels

**ZeroReels** is a free, local-first Windows app that turns a topic into a short-form video pipeline:

**Topic → Script → Scenes → Images → Voice-over → Captions → Motion → MP4**

ZeroReels is designed to work without paid AI APIs. Real generation is built around local tools such as Ollama, ComfyUI, Piper, whisper.cpp, and FFmpeg. A built-in Mock Mode lets you test the core pipeline before downloading large AI models.

## v0.3 test milestone

What is working in the current test build:

- Clean, uniform dark desktop UI with subtle hover, press, glow, and shadow effects
- 9:16, 16:9, and 1:1 output presets
- Local Ollama script + scene planning integration
- Local ComfyUI image-generation integration using an API workflow JSON
- Local Piper voice-over integration
- Timed SRT caption generation from scene narration
- whisper.cpp adapter included for later narration transcription workflows
- FFmpeg MP4 rendering with voice-over and subtle image motion
- Scene review screen with generated image previews and prompts
- Queue staging foundation for multiple topics
- Automatic project JSON saves during generation
- Local settings for AI tools and model paths
- Dependency diagnostics page
- Full Mock Mode end-to-end generation for testing without AI models
- Windows compile, UI smoke, model round-trip, and real MP4 render tests

## Not yet in v0.3

These are intentionally not advertised as complete yet:

- Burned-in animated social captions
- Automated background music and sound effects
- Cross-scene transition editor
- Per-scene edit/regenerate controls
- Automatic multi-item queue execution
- Project browser/load UI
- One-click local model installation

Those can be added after the v0.3 test proves the base pipeline is stable.

## First test

1. Install Python 3.11 or newer.
2. Clone or download this repository.
3. Run `setup.bat` once.
4. Run `run.bat`.
5. Keep **Mock Mode** enabled.
6. Start with a short test such as 15 seconds and 3 scenes.
7. Click **Generate Video**.
8. Verify that the progress bar completes, the Scenes page contains previews, and `final.mp4` opens from **Open Output**.

See [`docs/TESTING.md`](docs/TESTING.md) for the full checklist.

## Optional local tools for real generation

ZeroReels does not bundle large models or third-party binaries. Install the components you want and point ZeroReels to them in Settings:

- **Ollama** — script and scene generation
- **ComfyUI** — local image generation
- **Piper** — local text-to-speech
- **whisper.cpp** — optional transcription adapter
- **FFmpeg** — final video rendering (ZeroReels also includes an `imageio-ffmpeg` fallback)

### ComfyUI workflow placeholders

The ComfyUI API workflow JSON can use these tokens:

- `{{PROMPT}}`
- `{{WIDTH}}`
- `{{HEIGHT}}`
- `{{SEED}}`

ZeroReels replaces them before submitting the workflow to your local ComfyUI server.

## Project philosophy

- No paid API required
- No model files committed to Git
- Local-first and privacy-friendly
- Modular services so models can be swapped later
- Safe test mode before heavyweight installs
- Windows-first workflow

## Status

`v0.3.0` — first integrated test milestone.

## License

MIT. Third-party tools and models retain their own licenses. Check each model/tool license before commercial use.
