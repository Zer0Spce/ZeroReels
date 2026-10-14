# ZeroReels

**ZeroReels** is a free, local-first Windows desktop app that turns an idea into a finished short-form video.

**Topic → Script → Scene Images → Voice-over → Timed Captions → Motion/Transitions → MP4**

ZeroReels does not require a paid AI API. The production pipeline uses local tools and models on your Windows PC.

## v0.5 — Quality & Continuity

v0.5 focuses on making the finished reel feel more deliberately written, directed, voiced, and edited instead of like a sequence of unrelated AI slides.

### Cleaner Windows UI

- New **black + yellow** visual identity
- Compact Create dashboard designed for normal Windows laptop/desktop resolutions
- Cleaner hierarchy, tighter spacing, consistent cards and controls
- Subtle yellow button hover glow, press feedback, shadows, and active navigation effects
- **Create Live Generation Log** with timestamps for script, images, reused visuals, voice, captions, rendering, completion, and errors

### More human narration

- Stronger short-form script direction with less filler and fewer generic AI phrases
- Natural contractions, sentence-length variation, and spoken punctuation
- A second narration-only line-edit pass improves cadence without being allowed to add new facts
- Target-length voice pacing gently compensates when the generated script would otherwise run noticeably long or short
- Punctuation-aware pauses and subtle Kokoro delivery variation reduce metronomic narration
- Final narration receives light compression and loudness normalization during render

### Better visual continuity

Create now includes three continuity modes:

- **Consistent Story** — default; keeps recurring people, locations, props, wardrobe, era, and visual language coherent while still allowing natural shot changes
- **Same Cast & World** — stronger recurring character/world lock using a continuity bible plus a stable generation seed
- **Independent Shots** — allows fresh subjects per scene while keeping the overall art direction coherent

ZeroReels also performs a storyboard continuity pass. When two adjacent narration beats are clearly the same exact moment/location, it can **reuse the previous generated image** and change the camera motion/crop instead of unnecessarily inventing a new actor, room, or set.

Image prompts also explicitly avoid fake readable signs, documents, interfaces, labels, watermarks, and other text-heavy AI artifacts.

> Local diffusion consistency is best-effort. Same Cast & World improves continuity substantially, but it is not a biometric face-lock system.

### More natural editing

- Six subtle camera-motion patterns instead of a repeating three-motion loop
- Light image finishing for a more consistent final sequence
- Real scene-to-scene FFmpeg transitions instead of fading each still toward black
- Transition choices:
  - **Natural Crossfade** — default
  - **Soft Dissolve**
  - **Smooth Push**
  - **Clean Cut**

### Cleaner captions

Captions now break around phrases and punctuation instead of fixed word counts.

Caption position:
- **Bottom** — default
- **Safe Lower**
- **Center-Lower**

Caption size:
- **Small** — default
- **Medium**
- **Large**

The default is intentionally smaller and lower than v0.4 so it obstructs less of the generated scene.

## v0.4 — Real Local Pipeline

v0.4 moved ZeroReels beyond the v0.3 Mock Mode prototype and connected the full local generation pipeline:

- **Ollama + Qwen3 4B** for scripts and scene planning
- **ComfyUI Desktop + FLUX.2 Klein 4B** for local image generation
- **Kokoro-ONNX** for local voice-over with multiple narrator voices
- **FFmpeg** for motion, transitions, captions, audio processing, and H.264 MP4 export
- Actual voice duration drives scene timing and caption timing
- Built-in ComfyUI API workflow — no workflow JSON file to configure
- 9:16, 16:9, and 1:1 video output
- Burned subtitles when the FFmpeg build supports libass; `.srt` is retained as a fallback
- Project files and intermediate assets saved locally for inspection
- Windows-first Setup and Diagnostics pages
- One-click Ollama / ComfyUI installation through Windows Package Manager when available
- One-click local model/voice downloads
- Test Mode remains available for a fast end-to-end check without AI models
- Portable Windows build produced by GitHub Actions

## Recommended v0.5 defaults

For a typical story/documentary reel:

- Visual continuity: **Consistent Story**
- Caption position: **Bottom**
- Caption size: **Small**
- Transition style: **Natural Crossfade**
- Natural camera motion: **On**
- Scene transitions: **On**
- Burn captions: **On**

For a story that repeatedly shows the same person or fictional character, try **Same Cast & World**.

## Windows requirements

- Windows 10/11 (64-bit)
- An NVIDIA GPU is strongly recommended for FLUX.2 image generation
- Roughly **20+ GB free disk space** is recommended for the local AI stack and generated projects
- Real image generation is the heaviest part of the pipeline

ZeroReels itself can render videos without a discrete GPU, but ComfyUI image generation speed depends on your hardware.

## Easiest way to run

Download the latest **ZeroReels-Windows-Portable** build from GitHub Actions once a build is available, extract it, and run:

`ZeroReels.exe`

The portable app still downloads AI models separately on first-time setup; large model files are intentionally not bundled into the application ZIP.

## First-time AI setup

Open **Setup** inside ZeroReels and complete the four cards:

1. **Script AI** — install Ollama and download `qwen3:4b`.
2. **Image AI** — install/open ComfyUI Desktop, select its data folder, and download the FLUX.2 Klein model pack.
3. **Voice** — download the Kokoro local voice model and voice pack.
4. **Finish** — leave Ollama and ComfyUI running and confirm all checks in Diagnostics are green.

Then return to **Create**, enter a topic, choose a format/style/voice and quality options, and click **Generate Video**.

Detailed instructions: [`docs/REAL_SETUP.md`](docs/REAL_SETUP.md)

## Development run

Python development is supported on **Python 3.11–3.13**.

```bat
setup.bat
run.bat
```

Build the Windows portable folder locally with:

```bat
build.bat
```

The output is `dist\ZeroReels\ZeroReels.exe`.

## Where projects are saved

ZeroReels stores generated projects under:

`%USERPROFILE%\.zeroreels\projects\`

A project folder contains the generated images, per-scene voice files, combined narration, captions, `project.json`, and `final.mp4`.

When ZeroReels deliberately reuses a visual for adjacent narration beats, those scenes may reference the same generated source image while receiving different edit motion.

## Privacy and cost

- No paid API is required by the default pipeline.
- Prompts, generated images, narration, and projects remain on your PC when using the default local engines.
- Normal electricity, storage, and internet bandwidth for initial downloads still apply.

## Licenses

ZeroReels source code is MIT licensed. Third-party applications, libraries, and model files retain their own licenses. See [`THIRD_PARTY_NOTICES.md`](THIRD_PARTY_NOTICES.md).
