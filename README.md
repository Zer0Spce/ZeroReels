# ZeroReels

**ZeroReels** is a free, local-first Windows app that turns a topic into a short-form video pipeline:

**Topic → Script → Scenes → Images → Voice-over → Captions → Effects → MP4**

ZeroReels is designed to run without paid AI APIs. Real generation is powered by local tools such as Ollama, ComfyUI, Piper, whisper.cpp, and FFmpeg. A built-in Mock Mode lets you test the full app workflow before downloading large AI models.

## v0.3 test milestone

- Clean, uniform desktop UI with subtle hover/press effects and progress feedback
- 9:16, 16:9, and 1:1 output presets
- Local Ollama script generation
- Local ComfyUI image-generation integration
- Local Piper voice-over integration
- whisper.cpp caption integration
- FFmpeg renderer with image motion, fades, captions, music, and voice-over
- Scene review/edit/regenerate workflow
- Batch queue foundation
- Style, voice, subtitle, and motion presets
- Project save/load support
- Full-auto mode
- Mock Mode for end-to-end testing without AI models
- Dependency diagnostics page

## Quick start

1. Install Python 3.11+.
2. Clone this repository.
3. Run `setup.bat`.
4. Launch with `run.bat`.
5. Leave **Mock Mode** enabled for the first test.

```bash
python -m zeroreels
```

## Optional local tools for real generation

ZeroReels does not bundle large models or third-party binaries. Install the components you want and point ZeroReels to them in Settings:

- Ollama — script and scene generation
- ComfyUI — local image generation
- Piper — local text-to-speech
- whisper.cpp — local transcription/captions
- FFmpeg — final video rendering

## Project philosophy

- No paid API required
- No model files committed to Git
- Local-first and privacy-friendly
- Modular services so models can be swapped later
- Safe test mode before heavyweight installs
- Windows-first portable workflow

## Status

`v0.3-dev` — first integrated test milestone.

## License

MIT. Third-party tools and models retain their own licenses; check each model/tool license before commercial use.
