# ZeroReels

**ZeroReels** is a free, local-first Windows desktop app that turns an idea into a finished short-form video.

**Topic → Script → Directed Scene Images → Voice-over → Styled Captions → Professional Edit → MP4**

ZeroReels does not require a paid AI API. The default production pipeline runs locally with Ollama, ComfyUI/FLUX, Kokoro and FFmpeg.

## v0.6 — Professional Polish

v0.6 focuses on making the finished reel feel **directed and edited**, rather than like a sequence of AI stills.

### Professional story and shot direction

ZeroReels still uses the v0.5.3 TikTok/Reels writing system, then adds a stricter duration-fit and visual-direction pass.

Every scene receives an editing role such as:

- **Hook** — instantly readable opening event
- **Establishing** — wider environment and scale
- **Action** — candid physical story beat
- **Detail** — object/effect/B-roll close-up
- **Escalation** — consequence grows from a new angle
- **Peak** — strongest scale or reveal
- **Aftermath** — quieter contextual reset
- **Landing** — clean memorable final image

The prompt system deliberately asks for more B-roll and fewer repeated centered hero portraits. It also adds caption-safe framing guidance so important faces, hands and story objects are less likely to sit under subtitles or against the 9:16 crop edges.

### Duration fit

ZeroReels aims the spoken script at the requested duration instead of relying mainly on voice-speed changes.

- narration word count is checked against the target duration
- an extra rewrite pass is used when the draft is substantially short or long
- the rewrite is instructed to preserve existing facts and not invent new claims
- actual narration duration is saved in the project and shown against the target after generation

Duration remains approximate because local TTS timing varies with punctuation, voice and sentence structure.

### Scene Quality Guard

**Auto-regenerate weak scenes** is enabled by default for real image generation.

After each FLUX image, ZeroReels performs inexpensive local structural checks for:

- invalid/unreadable image files
- extreme darkness or overexposure
- unusually flat/low-detail frames
- strong center seams that can indicate split-panel/collage output
- near-duplicate imagery compared with the previous scene

A weak scene can be regenerated up to two times with a new deterministic seed and stronger single-frame instructions. The Live Log shows the quality score, reason and retry.

> The current Quality Guard is a heuristic image-structure checker. It is **not** a vision model and does not reliably detect every malformed hand, face or anatomy problem. Those remain best-effort limitations of the local image model.

### Continuity modes

- **Consistent Story** — recurring people/places/props remain coherent when they naturally recur
- **Hero Character Lock** — strongest recurring-person prompt/seed lock in the current local FLUX stack
- **Same Cast & World** — strong recurring cast/world traits with fresh shots
- **Independent Shots** — freer standalone visuals while preserving the selected art direction

Every scene still receives a **fresh generated image**.

> Hero Character Lock improves identity continuity through stable descriptions and deterministic seed families. It is **not** biometric face locking and does not use a dedicated image-reference identity model yet.

### Professional captions

v0.6 moves the polished caption path to ASS subtitles for richer local FFmpeg styling.

Caption styles:

- **TikTok Pop** — default; short phrase chunks, subtle pop-in scale, one yellow emphasized keyword
- **Clean Lower Third** — restrained lower caption with selective keyword emphasis
- **Documentary** — quieter traditional subtitle treatment

Existing placement and size controls remain:

- Bottom / Safe Lower / Center-Lower
- Small / Medium / Large

### Human-editor cut rhythm

**Story Rhythm** no longer transitions every scene.

For fast TikTok/social styles, most boundaries are **clean cuts** with occasional short crossfades used as punctuation. Mystery styles use a few restrained dissolves; documentary styles use occasional natural crossfades.

Manual transition choices remain available:

- Story Rhythm
- Natural Crossfade
- Soft Dissolve
- Smooth Push
- Clean Cut

### Adaptive motion and unified grade

Motion is chosen from the scene role instead of applying the same Ken Burns move repeatedly:

- hook push
- wide pan
- detail push
- reverse escalation pan
- scale reveal
- quiet aftermath drift
- slow landing

The edit also applies one restrained finishing language across the generated images: light contrast/saturation unification, subtle sharpening, very light grain and vignette.

### Local audio polish

New soundtrack modes:

- **Auto Ambience** — default; creates a very low local atmospheric bed with FFmpeg, no downloaded music required
- **Local Music Folder** — uses your own supported audio files from the folder selected in Settings
- **Off**

When a bed is used, ZeroReels applies sidechain ducking under narration. **Subtle transition SFX** can add a few very low-level local accents at selected edit points.

If the post-mix fails, ZeroReels keeps the already-rendered narration mix rather than losing the video.

> ZeroReels does not ship copyrighted commercial music. Local Music Folder is intended for audio you own or have permission to use.

### Better Create and Scenes feedback

Create adds controls for:

- Caption Style
- Soundtrack
- Subtle transition SFX
- Auto-regenerate weak scenes
- Hero Character Lock

The Scenes page now records useful production metadata per shot:

- shot role
- quality score
- regeneration count
- motion choice
- next transition
- quality notes
- image prompt

The Create Live Log reports regeneration attempts, quality decisions, narration timing, caption rendering, scene editing and audio post-mix stages.

## v0.5.3 — TikTok Storytelling + Real Live Stages

v0.5.3 established the current story engine and reliable worker-stage logging.

Narration profiles include:

- **TikTok Story** — recommended default; conversational hook, escalation, natural spoken rhythm and clean landing
- **Viral Explainer** — fast clear explanation without fake hype
- **Dark Curiosity** — restrained mystery/curiosity narration
- **Mini Documentary** — human documentary cadence with stronger factual restraint
- existing Cinematic Documentary, Dark Mystery, Clean Educational, Fast Social, Retro Film and Anime Inspired profiles

The script structure is retention-oriented: immediate hook → clear premise → distinct escalating beats → strongest consequence/reveal → clean final line. Repetition is checked before expensive image generation.

The Live Log receives stage events from the background worker and reports story planning, image generation, voice, captions, motion, transitions and final encoding instead of appearing frozen on a generic status message.

## v0.4 — Real Local Pipeline

v0.4 connected the complete local generation stack:

- **Ollama + Qwen3 4B** for scripts and scene planning
- **ComfyUI Desktop + FLUX.2 Klein 4B** for local image generation
- **Kokoro-ONNX** for local voice-over
- **FFmpeg** for motion, captions, transitions, audio processing and H.264 MP4 export
- actual voice duration drives scene timing and caption timing
- built-in ComfyUI API workflow — no manual workflow JSON required
- 9:16, 16:9 and 1:1 output
- local project/intermediate files for inspection
- Windows-first Setup and Diagnostics
- one-click local model/voice setup where supported
- Test Mode for a fast end-to-end run without AI models
- portable Windows build from GitHub Actions

## Recommended v0.6 defaults

For most narration/story reels:

- Style: **TikTok Story**
- Visual continuity: **Consistent Story**
- Caption style: **TikTok Pop**
- Caption position: **Bottom**
- Caption size: **Small**
- Transition style: **Story Rhythm**
- Natural camera motion: **On**
- Scene transitions: **On**
- Soundtrack: **Auto Ambience**
- Subtle transition SFX: **On**
- Auto-regenerate weak scenes: **On**

For a reel that repeatedly follows one important person or fictional lead, try **Hero Character Lock**. If identity drift is still noticeable, **Same Cast & World** may produce more variety at the cost of a looser face match.

## Windows requirements

- Windows 10/11 (64-bit)
- NVIDIA GPU strongly recommended for FLUX.2 image generation
- roughly **20+ GB free disk space** recommended for the local AI stack and generated projects
- real image generation is the heaviest part of the pipeline

ZeroReels itself can render videos without a discrete GPU, but ComfyUI generation speed and usable model size depend heavily on hardware.

## Easiest way to run

Download the latest **ZeroReels-Windows-Portable** artifact from GitHub Actions, extract it and run:

`ZeroReels.exe`

The portable app does not bundle the large AI model files. Complete Setup once after installing/updating ZeroReels.

## First-time AI setup

Open **Setup** inside ZeroReels and complete the four cards:

1. **Script AI** — install Ollama and download `qwen3:4b`.
2. **Image AI** — install/open ComfyUI Desktop, select its active data folder and download the FLUX.2 Klein model pack.
3. **Voice** — download the Kokoro local voice model and voice pack.
4. **Finish** — leave Ollama and ComfyUI running and confirm all Diagnostics checks are green.

Then return to **Create**, enter a topic, choose your options and click **Generate Video**.

Detailed setup: [`docs/REAL_SETUP.md`](docs/REAL_SETUP.md)

## Local music folder

To use your own background music:

1. Open **Settings**.
2. Choose **Local music folder**.
3. Select a directory containing supported `.mp3`, `.wav`, `.m4a`, `.aac`, `.flac`, or `.ogg` files.
4. In Create, choose **Local Music Folder** under Soundtrack.

ZeroReels deterministically chooses a track for the topic and ducks it under the narrator. Use only music you have the rights to use.

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

Output:

`dist\ZeroReels\ZeroReels.exe`

## Where projects are saved

ZeroReels stores generated projects under:

`%USERPROFILE%\.zeroreels\projects\`

A project folder contains the generated images, per-scene voice files, combined narration, styled caption file, `project.json`, and `final.mp4`.

## Privacy and cost

- No paid API is required by the default pipeline.
- Prompts, generated images, narration and project assets remain on your PC when using the default local engines.
- Normal electricity, storage and internet bandwidth for initial downloads still apply.

## Licenses

ZeroReels source code is MIT licensed. Third-party applications, libraries and model files retain their own licenses. See [`THIRD_PARTY_NOTICES.md`](THIRD_PARTY_NOTICES.md).
