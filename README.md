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

## OpenClaw Brain

Run the voice agent with OpenClaw as the reasoning backend:

```sh
uv run --extra qwen-asr myagent \
  --brain openclaw \
  --wake-config wake.toml \
  --device 3
```

The OpenClaw Gateway must be running on `127.0.0.1:18789`, with its OpenAI-compatible Chat Completions endpoint enabled. Pass the Gateway bearer token with `--openclaw-token` or `OPENCLAW_GATEWAY_TOKEN`. The default model is `openclaw/default`, and `--openclaw-session` keeps turns in one OpenClaw session.

## Local TaskBrain

TaskBrain keeps orchestration, tools, and memory in MyAgent. The default model
backend is the OpenAI API; any OpenAI-compatible local endpoint can still be
selected with `--taskbrain-url`.

```sh
uv run --extra qwen-asr myagent \
  --brain taskbrain \
  --taskbrain-model gpt-5.6-luna \
  --taskbrain-reasoning-effort none \
  --wake-config wake.toml \
  --device 3
```

Set `OPENAI_API_KEY` before starting the agent. The API key stays local to the
process and is sent only to the configured model endpoint.

The default memory file is `data/memory.json`. The first built-in tools are
`remember`, `recall`, and `return_to_standby`; custom tools can be registered through `ToolRegistry`.
MCP servers and skills are planned as adapters on top of this registry.

Enable local semantic memory retrieval with Qwen3 Embedding:

```sh
uv sync --extra vector-memory --extra qwen-asr --extra wake
uv run myagent \
  --brain taskbrain \
  --taskbrain-memory-backend lancedb \
  --taskbrain-memory data/memory.lancedb \
  --taskbrain-user-id default \
  --taskbrain-embedding qwen3-embedding-0.6b \
  --taskbrain-embedding-device mps \
  --wake-config wake.toml \
  --device 3
```

The agent stays alive until `Ctrl+C`. After a wake word, subsequent turns do
not require the wake word again; ten seconds of silence returns to wake-word
standby. `--max-turns` is no longer used as an automatic shutdown condition.
After a wake word, it says `我在` if no follow-up speech starts within 0.8 seconds.

Memory records are stored in LanceDB under `data/memory.lancedb`. Existing
`data/memory.json` records are imported once with `--taskbrain-memory-source`.

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

Run the main agent. It remains alive until `Ctrl+C`:

```sh
# After 10 seconds of silence during an active conversation, require wake again
uv run myagent --timeout 10

# Or using the alias
uv run myagent-run -t 10
```

Enable wake word gating with a sherpa-onnx KWS config:

```sh
uv run myagent --wake-config wake.toml
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
