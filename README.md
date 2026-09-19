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

Mandarin transcripts normalize common ASCII punctuation to Chinese punctuation.

## Listening

Listen from the microphone and save each detected utterance:

```sh
uv run myagent-listen
```

List available audio devices:

```sh
uv run myagent-listen --list-devices
```

Optionally transcribe each utterance after it is saved:

```sh
uv run myagent-listen --transcribe
```

Runtime output uses timestamped logs:

```text
2026-09-19 16:20:34 INFO myagent.voice.listen_cli - speech_started
```

## Voice Loop

Run a minimal local listen-transcribe-speak loop:

```sh
uv run myagent-voice-loop --device 4 --max-turns 1
```

The first voice loop replies by echoing the transcript through local TTS.

## Main Voice Agent

Run the main agent with a standby timeout ($t$ seconds):

```sh
# Standby for 10 seconds (default); auto-shutdown if no speech detected
uv run myagent --timeout 10

# Or using the alias
uv run myagent-run -t 10
```

Continuous standby mode (resets $t$ seconds timeout after each reply):

```sh
uv run myagent --timeout 10 --continuous
```

## Notes

- Keep the README lightweight until the core design is decided.
- Add setup, usage, and architecture notes only after they match the actual implementation.
