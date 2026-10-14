# ZeroReels v0.4 — Real Windows Setup

This guide is for the **real local AI pipeline**, not Test Mode.

## 1. Launch ZeroReels

Use the portable `ZeroReels.exe`, or run `setup.bat` followed by `run.bat` from source.

Open the **Setup** page.

## 2. Script AI — Ollama

Click **Install Ollama**. ZeroReels uses Windows Package Manager (`winget`) when available.

After installation, click **Download Script Model**. The default is `qwen3:4b`.

Ollama normally exposes its local API at:

`http://127.0.0.1:11434`

## 3. Image AI — ComfyUI + FLUX.2 Klein

Click **Install ComfyUI Desktop** and launch ComfyUI Desktop once.

Then click **Detect / Select Data Folder**. Select the ComfyUI base/data folder containing the `models` directory.

Click **Download FLUX.2 Model Pack**. This is a large download (roughly 15 GB+ total).

ZeroReels installs these model files into the selected ComfyUI data folder:

- `models\text_encoders\qwen_3_4b.safetensors`
- `models\diffusion_models\flux-2-klein-4b.safetensors`
- `models\vae\flux2-vae.safetensors`

Restart ComfyUI after the files finish downloading if it was already open.

ComfyUI must be running at the configured local address (default `http://127.0.0.1:8188`) when ZeroReels generates images.

## 4. Voice — Kokoro

Click **Download Kokoro Voice Files**.

ZeroReels saves the local voice model under:

`%USERPROFILE%\.zeroreels\tts\`

The Create page includes a narrator selector. The default is `af_heart`.

## 5. Diagnostics

Open **Diagnostics** and run the checks.

A real generation requires these to be ready:

- Ollama
- Script model
- ComfyUI
- FLUX.2 nodes
- FLUX.2 diffusion model
- FLUX.2 text encoder
- FLUX.2 VAE
- Kokoro
- Voice model
- Voice pack
- FFmpeg

If ComfyUI is marked offline, launch ComfyUI Desktop and wait until its server finishes starting.

## 6. Generate a real video

On **Create**:

- Leave **Test Mode** OFF.
- Enter a topic.
- Choose output format, visual style, duration, scene count, and narrator.
- Keep captions, motion, and transitions enabled for the default polished output.
- Click **Generate Video**.

ZeroReels will create the script first, then images one at a time, generate narration, derive actual timings, generate captions, and render the final MP4.

## Troubleshooting

### Ollama offline
Open Ollama from the Start menu and retry Diagnostics.

### ComfyUI offline
Launch ComfyUI Desktop. Check that it is using port `8188`, or change the ComfyUI URL in Settings.

### FLUX files missing
Confirm the selected ComfyUI data folder is the folder that directly contains `models` and run the FLUX download again.

### Out of VRAM
Reduce other GPU workloads before generating. ZeroReels uses a lower image-generation resolution than the final video resolution to reduce VRAM pressure, then upscales during rendering.

### Captions not burned into the MP4
Some FFmpeg builds do not include the subtitle filter. ZeroReels will still finish the MP4 and keep `captions.srt` beside it rather than failing the whole render.
