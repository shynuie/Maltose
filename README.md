# MyAgent

MyAgent is an early-stage personal assistant project.

The implementation and architecture are still being explored. This repository will be updated as the project direction becomes clearer.

## Status

Initial setup. The first implemented area is the local voice system.

## TTS

Create the environment and install the project:

```sh
uv sync
```

Speak text with the macOS local TTS provider:

```sh
uv run myagent-tts "Hello from MyAgent"
```

Write audio to a file:

```sh
uv run myagent-tts "Hello from MyAgent" --output hello.aiff
```

## STT

Transcribe an audio file locally with faster-whisper:

```sh
uv run myagent-stt --file input.wav
```

The default STT language hint is Mandarin Chinese:

```sh
uv run myagent-stt --file input.wav --language zh
```

## Notes

- Keep the README lightweight until the core design is decided.
- Add setup, usage, and architecture notes only after they match the actual implementation.
