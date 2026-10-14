# Third-Party Notices

ZeroReels is MIT licensed, but it interoperates with or depends on third-party software and models that keep their own licenses.

This file is informational and is not a substitute for the license files distributed by each project.

## Ollama

Used as the local LLM runtime for script generation.

Project: https://github.com/ollama/ollama

## Qwen3

Default script model: `qwen3:4b` through Ollama.

The model listing identifies the model license as Apache License 2.0. Users should review the model license supplied by the model distributor before use.

## ComfyUI

Used as the local image-generation runtime.

Project: https://github.com/Comfy-Org/ComfyUI

## FLUX.2 Klein 4B

Default local image model. ZeroReels downloads the official ComfyUI-compatible model files into the user's ComfyUI model directories.

Users should review the license and model card supplied with the model before use.

## Kokoro-ONNX / Kokoro

`kokoro-onnx` wrapper: MIT License.

Kokoro model: Apache License 2.0 according to the kokoro-onnx project documentation.

Project: https://github.com/thewh1teagle/kokoro-onnx

## Chatterbox TTS (optional)

v0.7 can optionally create a separate local Python environment and install `chatterbox-tts` for Chatterbox Nano reference-voice generation. It is not bundled into the ZeroReels portable ZIP.

Project: https://github.com/resemble-ai/chatterbox

Chatterbox model/package licensing and model-card terms remain separate from ZeroReels. Users should review the upstream license and model documentation before use.

## F5-TTS (optional)

v0.7 can optionally create a separate local Python environment and install `f5-tts` for reference-voice generation. It is not bundled into the ZeroReels portable ZIP.

Project: https://github.com/SWivid/F5-TTS

F5-TTS package/model licensing remains separate from ZeroReels. Users should review the upstream license and model-card terms before use.

## Tesseract OCR (optional)

Visual QA v2 can use an existing local Tesseract executable to reject generated frames containing readable text. Tesseract is optional and is not bundled by ZeroReels.

Project: https://github.com/tesseract-ocr/tesseract

## FFmpeg / imageio-ffmpeg

Used for video encoding and rendering. FFmpeg builds may be LGPL or GPL depending on compile-time options. The exact license information for the binary distributed through `imageio-ffmpeg` should be reviewed with that package/binary.

## PySide6 / Qt

Used for the Windows desktop interface. Qt/PySide licensing terms apply separately.
