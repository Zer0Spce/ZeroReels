# Fish Audio Drama 3 in ZeroReels

ZeroReels v0.8.3 adds **Fish Audio Drama 3 (Server)** as an optional reference-voice TTS engine.

Drama 3 is not bundled with the portable app. The official checkpoint is roughly 41.5 GB and the current Fish Audio runtime documentation targets Linux/WSL with a large NVIDIA GPU (about 48 GB VRAM for the full FP8 model). That makes direct local inference impractical on typical laptop GPUs, including 6 GB RTX 3060-class hardware.

ZeroReels therefore connects to a separate OpenAI-compatible Drama 3 speech server while the rest of the video pipeline can remain on the Windows machine.

## Start a compatible server

A current SGLang-Omni example is:

```bash
git clone https://github.com/sgl-project/sglang-omni.git
cd sglang-omni
uv pip install --prerelease=allow -v -e ".[fishaudio]"
sgl-omni serve --model-path fishaudio/drama-3 --port 8000
```

The server can be on another workstation, a GPU server, or a suitable cloud GPU. Do not expose an unauthenticated inference server directly to the public internet.

## Configure ZeroReels

1. Open **Settings**.
2. Under **Fish Audio Drama 3**, enter the server endpoint. The default is `http://127.0.0.1:8000`.
3. Keep the model ID as `fishaudio/drama-3` unless the server exposes it under another ID.
4. If the server requires a bearer token, enter it in the optional API-key field (or set `ZEROREELS_DRAMA3_API_KEY`).
5. Choose a clean **Natural voice reference WAV** and enter the exact **Reference transcript**.
6. Save Settings.
7. Open **Setup → Voice → Test Drama 3 Server**.
8. On Create, choose **Fish Audio Drama 3 (Server)** as the Voice engine.

ZeroReels sends the reference clip as a data URL so the Drama 3 server does not need access to the Windows filesystem. Long narration is split on sentence boundaries and assembled back into one WAV before captions and runtime locking continue.

If the Drama 3 server cannot be reached, ZeroReels attempts the local Chatterbox Turbo Fast Clone path when installed, then Kokoro Directed as the final reliability fallback.

## Voice and licensing note

**Built with Fish Audio** when this engine is used.

Drama 3 is governed by Fish Audio's license, not ZeroReels' MIT license. Review the license shipped with the model before using it. Current terms include restrictions around hosted services and require consent or another legal right before cloning an identifiable person's voice. Commercial-use conditions also depend on the license's revenue threshold and other terms.

ZeroReels does not download or redistribute the Drama 3 weights.
