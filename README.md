# ZeroReels

**ZeroReels** is a free, local-first Windows desktop app that turns an idea into a finished short-form video.

**Topic → Script → Scene Images → Voice-over → Timed Captions → Motion/Transitions → MP4**

ZeroReels does not require a paid AI API. The production pipeline uses local tools and models on your Windows PC.

## v0.5.3 — TikTok Storytelling + Real Live Stages

v0.5.3 focuses on the two things that matter most after the real local pipeline works: **better storytelling** and **clear feedback while the app is working**.

### Real Create Live Log

The Create log now consumes stage events directly from the background generation worker instead of relying on a generic heartbeat.

It reports real pipeline work such as:

- initializing and checking the local stack
- planning the story
- drafting and polishing narration
- checking repetition/flow
- generating each image and confirming when each image is ready
- generating voice-over
- building captions
- rendering motion clips
- compositing transitions
- encoding the final MP4

If one local AI operation takes a long time, ZeroReels keeps an elapsed-time heartbeat for the **current real stage** instead of remaining stuck on `Preparing local pipeline`.

### TikTok Story is the new recommended default

Create now includes four additional narration profiles:

- **TikTok Story** — default; conversational hook, escalation, natural spoken rhythm, memorable landing
- **Viral Explainer** — fast, clear explanation without fake hype
- **Dark Curiosity** — restrained mystery/curiosity narration
- **Mini Documentary** — human documentary cadence with stronger factual restraint

Existing visual styles remain available.

The v0.5.3 script planner uses a retention-oriented structure:

1. immediate concrete hook
2. clear premise
3. distinct escalating beats
4. strongest consequence/reveal near the end
5. clean final line instead of a generic CTA

The script is then line-edited for contractions, sentence variety, spoken punctuation, pacing, and repetition. Factual topics are instructed not to invent dates, quotes, statistics, studies, or events. Hypothetical topics are written as plausible consequences rather than fake sourced facts.

### Better visual storytelling

Every scene now receives a distinct visual role instead of merely receiving another generic prompt. Across an eight-scene reel ZeroReels deliberately varies beats such as:

- hook image
- establishing shot
- medium action
- meaningful close detail
- escalation angle
- largest-impact visual
- aftermath/context
- final reflective image

Continuity still preserves recurring cast/world traits, but **every scene generates a fresh image**. ZeroReels does not reuse the exact previous frame for continuity.

- **Consistent Story** — coherent recurring people, locations, props, era, palette, and production design with fresh framing per scene
- **Same Cast & World** — stronger recurring character/world lock with a deterministic seed family, not one identical seed
- **Independent Shots** — freer standalone visuals while retaining the selected visual style

Prompts explicitly discourage duplicated subjects, poster-like repetition, fake readable documents, signs, interfaces, labels, logos, watermarks, and subtitles inside generated images.

> Local diffusion identity consistency is best-effort. Same Cast & World improves recurring-character coherence, but it is not a biometric face-lock system.

### Story Rhythm transitions

**Story Rhythm** is the new recommended transition mode. It adapts transition timing to the selected story style:

- TikTok Story / Viral Explainer / Fast Social → quicker, almost-cut crossfades
- Dark Curiosity / Dark Mystery → softer dissolves
- Mini Documentary / Cinematic Documentary → restrained natural crossfades

Manual options remain available:

- Natural Crossfade
- Soft Dissolve
- Smooth Push
- Clean Cut

### Repetition and quality guard

Before spending time on FLUX image generation, ZeroReels checks whether scene narration collapsed into duplicates or near-duplicates. It attempts a focused repair pass. If the local model still repeats itself, generation stops early instead of wasting several minutes creating a broken reel.

## v0.5 — Quality & Continuity foundation

The v0.5 series added the black/yellow Windows UI, compact Create dashboard, Create Live Log, phrase-aware captions, lower/smaller caption defaults, six camera-motion patterns, visual continuity modes, humanized Kokoro pacing, light image finishing, audio compression/loudness normalization, and FFmpeg scene-to-scene transitions.

### Cleaner captions

Caption position:
- **Bottom** — default
- **Safe Lower**
- **Center-Lower**

Caption size:
- **Small** — default
- **Medium**
- **Large**

The default is intentionally small and low so captions cover less of the generated image.

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

## Recommended v0.5.3 defaults

For most narration/story reels:

- Style: **TikTok Story**
- Visual continuity: **Consistent Story**
- Caption position: **Bottom**
- Caption size: **Small**
- Transition style: **Story Rhythm**
- Natural camera motion: **On**
- Scene transitions: **On**
- Burn captions: **On**

For a story that repeatedly shows the same person or fictional character, use **Same Cast & World**.

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

## Privacy and cost

- No paid API is required by the default pipeline.
- Prompts, generated images, narration, and projects remain on your PC when using the default local engines.
- Normal electricity, storage, and internet bandwidth for initial downloads still apply.

## Licenses

ZeroReels source code is MIT licensed. Third-party applications, libraries, and model files retain their own licenses. See [`THIRD_PARTY_NOTICES.md`](THIRD_PARTY_NOTICES.md).
