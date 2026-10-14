# ZeroReels v0.4 Test Checklist

## Portable app

- [ ] `ZeroReels.exe` starts without a console window.
- [ ] Main window opens with six pages: Create, Scenes, Queue, Setup, Settings, Diagnostics.
- [ ] Buttons show subtle hover/press feedback and UI spacing remains consistent at 100% and 125% Windows scale.

## Test Mode

- [ ] Enable Test Mode.
- [ ] Generate a 15-second, 3-scene 9:16 video.
- [ ] Progress reaches 100%.
- [ ] `final.mp4` opens.
- [ ] Scene cards populate.
- [ ] Project folder opens.

## Real setup

- [ ] Install/detect Ollama.
- [ ] Pull `qwen3:4b`.
- [ ] Install/open ComfyUI Desktop.
- [ ] Select the ComfyUI data folder.
- [ ] Download FLUX.2 Klein files.
- [ ] Download Kokoro model + voices.
- [ ] Diagnostics shows all required production checks green.

## Real generation

- [ ] Leave Test Mode OFF.
- [ ] Generate a 15-second, 3-scene test reel first.
- [ ] Ollama returns a valid script and exactly 3 scenes.
- [ ] ComfyUI generates all 3 scene images.
- [ ] Kokoro generates intelligible narration.
- [ ] Scene durations match the actual narration rather than the requested target estimate.
- [ ] Captions roughly follow narration scene timing.
- [ ] Final MP4 is H.264/AAC and plays in Windows Media Player.
- [ ] Motion is subtle and not nauseating.
- [ ] Fade effects are clean.
- [ ] Captions either burn into the video or remain as a valid SRT fallback.
