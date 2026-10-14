# ZeroReels

**ZeroReels** is a free, local-first Windows desktop app that turns an idea into a finished short-form video.

**Topic → Script → Voice Director → Directed Scene Images → Styled Captions → Human-Style Edit → MP4**

ZeroReels does not require a paid AI API. The default production pipeline runs locally with Ollama, ComfyUI/FLUX, Kokoro and FFmpeg. Optional natural-voice engines remain local too.

## v0.7 — Human Touch

v0.7 targets the remaining things that make an otherwise good reel still feel AI-generated: flat narration, guessed runtime, repetitive framing, readable AI text, overly even caption pacing and generic sound beds.

### Voice Director

**Kokoro Directed** is the new default voice mode. Instead of resetting the narrator at every scene, ZeroReels performs the narration as one continuous delivery whenever the local Kokoro build can handle it, with a two-scene block fallback for long inputs.

Delivery presets:

- **Natural Storyteller** — recommended default
- **Curious**
- **Serious Documentary**
- **Dark Mystery**
- **Energetic Explainer**

The final audio chain also uses gentler compression and a wider loudness range than v0.6 so hooks, reveals, pauses and landing lines keep more natural emphasis.

**Kokoro Classic** remains available.

### Optional natural local voices

Setup can create isolated Python 3.11 environments for two optional free local engines:

- **Chatterbox Nano** — small CPU-friendly reference-voice engine; useful on systems where ComfyUI already occupies most GPU memory
- **F5-TTS Studio** — heavier reference-voice option for users who want another natural local TTS choice

These optional engines are not bundled into the portable ZIP. Click their install buttons under **Setup → Voice**. Their Python packages and model weights have separate third-party licenses and large first-use downloads.

Both reference-based engines require a short voice clip selected under **Settings → Natural voice reference WAV**. F5-TTS benefits from entering the exact transcript of that reference clip.

### Measured runtime lock

ZeroReels no longer relies only on estimated words-per-minute for the final duration.

The v0.7 order is:

1. write and polish the narration
2. perform the narration once
3. measure the actual WAV
4. if the result misses the requested duration by more than about 5%, run one focused runtime rewrite that preserves the existing facts and visual beats
5. perform the corrected narration
6. only then spend time generating FLUX images

This prevents a nominal 60-second request from silently becoming a much shorter reel after image generation is already complete.

### Dynamic visual pacing

**Dynamic visual pacing** is enabled by default. For longer reels, ZeroReels can increase a sparse manual scene count toward roughly one meaningful visual beat every five seconds, capped at 14 scenes.

Examples:

- 30 seconds / 8 requested scenes → keeps 8
- 45 seconds / 8 requested scenes → approximately 9 beats
- 60 seconds / 8 requested scenes → approximately 12 beats

The director also tells neighboring scenes to differ clearly in subject scale, camera height, lens distance or viewing angle, while keeping important subjects away from the lower caption-safe area.

### Visual QA v2

The v0.6 quality guard is expanded with:

- split-panel/contact-sheet checks at thirds, halves and two-thirds
- composition signatures that catch repeated recent framing
- near-duplicate scene checks
- stronger single-frame retry prompts
- explicit avoidance of readable documents, maps, screens, labels and signs
- optional **Tesseract OCR** rejection when Tesseract is available

If OCR finds multiple readable words where ZeroReels did not request text, the scene is treated as a failed visual and can be regenerated automatically.

> Visual QA v2 is still a lightweight local heuristic system, not a full vision-language model. It substantially improves repeated/collage/text failures but cannot guarantee perfect anatomy or faces.

### Speech-paced social captions

TikTok Pop captions are now broken into shorter phrase units, with timing weighted by phrase length instead of fixed word blocks.

New placement option:

- **Auto Safe** — recommended default; adjusts lower margin by the director's shot role

Long phrases automatically shrink slightly instead of forcing awkward wraps. Keyword emphasis and the subtle pop/fade remain restrained.

### Human-style sound design

**Smart Soundscape** is the new default soundtrack mode. It chooses a very low local ambience character from the topic/script, such as water/rain, urban air, wind, low-tech atmosphere, dark room tone or neutral room tone.

Sound design remains intentionally sparse:

- narration stays dominant
- ambience ducks under speech
- transition SFX are limited mainly to escalation/peak beats
- Local Music Folder remains available for audio you own or have permission to use
- Off remains available

No commercial music is bundled.

### Human Touch Create controls

Create adds:

- Voice Engine
- Voice Delivery
- Measured Runtime Lock
- Dynamic Visual Pacing
- Visual QA v2
- Reject Readable AI Text
- Auto Safe captions
- Smart Soundscape

The Live Generation Log reports the measured voice pass, runtime correction, per-scene Visual QA decisions, caption timing, edit pass and semantic sound design.

## v0.6 — Professional Polish

v0.6 established the professional editing foundation: shot roles, quality scoring/regeneration, Story Rhythm mostly-clean cuts, adaptive motion, unified light grade, TikTok Pop ASS captions, soundtrack ducking and richer Scenes metadata.

### Directed shot roles

Each scene receives an editing role such as:

- **Hook** — instantly readable opening event
- **Establishing** — wider environment and scale
- **Action** — candid physical story beat
- **Detail** — object/effect/B-roll close-up
- **Escalation** — consequence grows from a new angle
- **Peak** — strongest scale or reveal
- **Aftermath** — quieter contextual reset
- **Landing** — clean memorable final image

The prompt system asks for more B-roll and fewer repeated centered hero portraits.

### Continuity modes

- **Consistent Story** — recurring people/places/props remain coherent when they naturally recur
- **Hero Character Lock** — strongest recurring-person prompt/seed lock in the current local FLUX stack
- **Same Cast & World** — strong recurring cast/world traits with fresh shots
- **Independent Shots** — freer standalone visuals while preserving the selected art direction

Every scene receives a fresh generated image.

> Hero Character Lock improves identity continuity through stable descriptions and deterministic seed families. It is not biometric face locking and does not use a dedicated image-reference identity model.

### Caption styles

- **TikTok Pop** — short social phrases, subtle pop-in, yellow emphasized keyword
- **Clean Lower Third**
- **Documentary**

Sizes: Small / Medium / Large.

### Story Rhythm

Most fast social boundaries are clean cuts. Short crossfades/dissolves are used as punctuation rather than decoration. Manual Natural Crossfade, Soft Dissolve, Smooth Push and Clean Cut remain available.

## v0.5.3 — TikTok Storytelling + Real Live Stages

Narration profiles include:

- **TikTok Story** — recommended default
- **Viral Explainer**
- **Dark Curiosity**
- **Mini Documentary**
- Cinematic Documentary, Dark Mystery, Clean Educational, Fast Social, Retro Film and Anime Inspired

The story engine follows immediate hook → clear premise → distinct escalation → strongest consequence/reveal → clean final line, with repetition checks before expensive image generation.

The Create Live Log receives real stage events from the background worker instead of appearing frozen on a generic status message.

## v0.4 — Real Local Pipeline

v0.4 connected the local production stack:

- **Ollama + Qwen3 4B** for script/story planning
- **ComfyUI Desktop + FLUX.2 Klein 4B** for local images
- **Kokoro-ONNX** for built-in local narration
- **FFmpeg** for motion, captions, cuts/transitions, audio and H.264 MP4 export
- 9:16, 16:9 and 1:1 output
- local project/intermediate files
- Windows Setup and Diagnostics
- Test Mode
- portable Windows build through GitHub Actions

## Recommended v0.7 defaults

For most narration/story reels:

- Style: **TikTok Story**
- Visual continuity: **Consistent Story**
- Voice engine: **Kokoro Directed**
- Voice delivery: **Natural Storyteller**
- Measured runtime lock: **On**
- Dynamic visual pacing: **On**
- Caption style: **TikTok Pop**
- Caption position: **Auto Safe**
- Caption size: **Small**
- Transition style: **Story Rhythm**
- Natural camera motion: **On**
- Scene transitions: **On**
- Soundtrack: **Smart Soundscape**
- Subtle SFX: **On**
- Visual QA v2: **On**
- Reject readable AI text: **On**

For a reel that repeatedly follows one important person or fictional lead, try **Hero Character Lock**.

## Windows requirements

- Windows 10/11 (64-bit)
- NVIDIA GPU strongly recommended for FLUX.2 image generation
- roughly **20+ GB free disk space** for the default local AI stack and generated projects
- optional Chatterbox/F5 environments require additional disk space and their own first-use model downloads

The default Kokoro Directed engine remains the lightweight option. Chatterbox Nano deliberately runs on CPU in ZeroReels so it does not compete with ComfyUI for VRAM on 6 GB-class GPUs.

## Easiest way to run

Download the latest **ZeroReels-Windows-Portable** artifact from GitHub Actions, extract it and run:

`ZeroReels.exe`

The portable app does not bundle the large AI model files. Complete Setup once after installing/updating ZeroReels.

## First-time AI setup

Open **Setup** and complete the four cards:

1. **Script AI** — install Ollama and download `qwen3:4b`.
2. **Image AI** — install/open ComfyUI Desktop, select its active data folder and download the FLUX.2 Klein model pack.
3. **Voice** — download the Kokoro model/voice pack. Optional Chatterbox Nano/F5-TTS installers are in this same card.
4. **Finish** — leave Ollama and ComfyUI running and confirm required Diagnostics checks are green.

For Chatterbox Nano or F5-TTS Studio, also choose a short clean reference voice WAV in Settings before generating.

Detailed setup: [`docs/REAL_SETUP.md`](docs/REAL_SETUP.md)

## Local music folder

To use your own background music:

1. Open **Settings**.
2. Choose **Local music folder**.
3. Select a directory containing supported `.mp3`, `.wav`, `.m4a`, `.aac`, `.flac`, or `.ogg` files.
4. In Create, choose **Local Music Folder** under Soundtrack.

Use only music you have the rights to use.

## Development run

Python development is supported on **Python 3.11–3.13**.

```bat
setup.bat
run.bat
```

Build the portable Windows folder locally with:

```bat
build.bat
```

Output:

`dist\ZeroReels\ZeroReels.exe`

## Where projects are saved

ZeroReels stores generated projects under:

`%USERPROFILE%\.zeroreels\projects\`

A project folder contains generated images, narration, styled captions, `project.json`, intermediate files and `final.mp4`.

Optional natural voice environments are stored under:

`%USERPROFILE%\.zeroreels\voice\`

## Privacy and cost

- No paid API is required by the default pipeline.
- Prompts, generated images, narration and project assets remain on your PC when using the local engines.
- Optional voice-engine package/model downloads are free but can be large.
- Normal electricity, storage and internet bandwidth for initial downloads still apply.

## Licenses

ZeroReels source code is MIT licensed. Third-party applications, libraries and model files retain their own licenses. See [`THIRD_PARTY_NOTICES.md`](THIRD_PARTY_NOTICES.md).
