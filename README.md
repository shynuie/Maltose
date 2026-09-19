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

The default provider is local Qwen3-ASR-0.6B. Fun-ASR-Nano and faster-whisper remain available for comparison:

```sh
uv run --extra funasr myagent-stt --provider fun-asr-nano --file input.wav --language zh
```

Fun-ASR-Nano is currently experimental. It runs locally on Apple Silicon CPU, but needs a larger model download and may retain or misrecognize part of the wake word.

MPS can be selected for testing with `--stt-device mps`, but CPU is currently the default because the tested Nano path was faster on CPU.

Qwen3-ASR-0.6B is also available as a local provider:

```sh
uv run --extra qwen-asr myagent-stt --provider qwen3-asr-0.6b --file input.wav --language zh
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

Enable wake word gating with a sherpa-onnx KWS config:

```sh
uv run myagent --wake-config wake.toml --continuous
```

Speak a short acknowledgement after wake detection:

```sh
uv run --extra wake myagent --wake-config wake.toml --device 3 --wake-ack 我在 --wake-ack-delay 0.8
```

With `--wake-ack`, MyAgent waits briefly for follow-up speech after the wake word.
If speech starts before the delay expires, it processes the command directly; otherwise it says the acknowledgement.
For one-shot commands, MyAgent keeps `--wake-buffer-ms 1000` of audio before wake detection and prepends it when follow-up speech starts.

Wake word detection also applies conservative frame-level peak normalization before sherpa-onnx KWS by default.
Configure it in `wake.toml` with `normalize_audio`, `target_peak`, `min_peak`, and `max_gain`.

Before Whisper STT, captured utterances are conservatively peak-normalized by default.
The default target is `--stt-target-peak 12000`, applied only when peak is below `--stt-min-peak 6000`, capped by `--stt-max-gain 4.0`.
Disable it with `--no-normalize-stt-audio`.

Monitor wake word detection and input volume live:

```sh
uv run --extra wake myagent-wake-monitor --wake-config wake.toml --device 3
```

Test the two-stage wake listening flow:

```sh
uv run --extra wake myagent-listen --wake-config wake.toml --device 3 --max-utterances 1 --transcribe
```

Example `wake.toml`:

```toml
[wake]
enabled = true
provider = "sherpa-onnx"

[wake.sherpa_onnx]
tokens = "models/sherpa-onnx-kws/tokens.txt"
encoder = "models/sherpa-onnx-kws/encoder.onnx"
decoder = "models/sherpa-onnx-kws/decoder.onnx"
joiner = "models/sherpa-onnx-kws/joiner.onnx"
keywords_file = "models/sherpa-onnx-kws/keywords.txt"
keywords_threshold = 0.25
keywords_score = 1.0
num_threads = 1
provider = "cpu"
```

The `keywords_file` is the tokenized sherpa-onnx KWS keyword file, not raw text.
Generate it from raw keywords with the model's matching `tokens.txt` and token type.

## Notes

- Keep the README lightweight until the core design is decided.
- Add setup, usage, and architecture notes only after they match the actual implementation.
