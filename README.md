# MyAgent

Architecture overview: open [ARCHITECTURE.html](ARCHITECTURE.html) for a
standalone visual flow diagram, or read [ARCHITECTURE.md](ARCHITECTURE.md) for
the Markdown/Mermaid version.

TaskBrain can stream compatible LLM responses to VoiceAgent. Responses are
buffered until sentence punctuation (including `。`, `！`, `？`, `；`, and their
ASCII forms), then spoken one segment at a time with the ending punctuation
preserved. Commas remain buffered to avoid overly short or unnatural speech
segments. The model stream is read in the background while TTS speaks the
already completed segment. Endpoints must support OpenAI-compatible `stream:
true` SSE output.

MyAgent is a local voice assistant with wake-word detection, speech recognition,
TaskBrain orchestration, user-scoped memory, web search, and optional MCP tools.

## Status

The main runtime configuration lives in `myagent.toml`. CLI flags remain
available as temporary overrides.

Development planning and architecture progress are centralized under
[dev/](dev/README.md), with the project roadmap in
[dev/major_plan.md](dev/major_plan.md) and feature-level plans in
`dev/features/`.

## Quick Start

Install the runtime extras used by the current voice setup:

```sh
uv sync --extra wake --extra qwen-asr --extra vector-memory --extra speaker
```

Create the unified configuration:

```sh
cp myagent.toml.example myagent.toml
```

Put API credentials in `.env`:

```env
OPENAI_API_KEY=...
BRAVE_SEARCH_API_KEY=...
```

Start the assistant:

```sh
./start
```

`./start` 會同時啟動 Agent 與文件 watcher；Agent 結束時會一併停止 watcher。
若只需要手動 indexing，可直接使用 `uv run myagent-documents index`。

The example configuration uses microphone device `3`, `wake.toml`, Qwen3-ASR,
LanceDB memory, Brave search, and the `default` user. Change these values in
`myagent.toml`; the file is ignored by Git because it may contain local paths
or credentials.

Use another configuration file when needed:

```sh
./start --config another-config.toml
```

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

The recommended command is the short command in **Quick Start**. The equivalent
long-form flags are still supported for one-off overrides.

Set `OPENAI_API_KEY` before starting the agent. The API key stays local to the
process and is sent only to the configured model endpoint.

The default memory backend is LanceDB. The first built-in tools are
`remember`, `recall`, and `return_to_standby`; custom tools can be registered through `ToolRegistry`.
MCP servers and Skills are exposed through capability adapters. Add stdio MCP
servers in `myagent.toml`:

```toml
[taskbrain]
mcp_command = [
  "npx -y your-slack-mcp-server",
  "npx -y your-gmail-mcp-server",
]
```

The server commands must speak MCP JSON-RPC over stdin/stdout. Their tools are
exposed to the model with names such as `mcp_0_search_messages`.

Enable local semantic memory retrieval with Qwen3 Embedding:

```toml
[taskbrain]
memory_backend = "lancedb"
memory = "data/memory/memory.lancedb"
user_id = "user-001"
embedding = "qwen3-embedding-0.6b"
embedding_device = "mps"
```

The agent stays alive until `Ctrl+C`. After a wake word, subsequent turns do
not require the wake word again; ten seconds of silence returns to wake-word
standby. `--max-turns` is no longer used as an automatic shutdown condition.
After a wake word, it says `我在` if no follow-up speech starts within 0.8 seconds.

Memory records are stored in LanceDB under `data/memory/memory.lancedb`. The legacy
`data/memory/memory.json` store is not used at runtime; current identity-scoped data
uses the sequential system user ID from `user_profile`.

## Document Knowledge Base

The Document Knowledge Base stores original documents under the configurable
`documents_root` and keeps its metadata and vectors separate from Memory:

```text
documents/
├── inbox/
├── personal/
├── work/
├── projects/
├── papers/
├── notes/
└── archive/
```

Install the vector and PDF dependencies before indexing:

```sh
uv sync --extra wake --extra qwen-asr --extra vector-memory --extra speaker
```

Index, list, and search documents with the dedicated CLI:

```sh
uv run myagent-documents index
uv run myagent-documents index --force
uv run myagent-documents repair
uv run myagent-documents repair --prune-orphans
uv run myagent-documents queue
uv run myagent-documents queue --status failed
uv run myagent-documents list
uv run myagent-documents search "我的碩士論文"
uv run myagent-documents watch
```

`watch` 會在目前 process 中持續監控 `documents/`，自動處理新增、修改、移動與刪除。可用 `--poll-interval` 調整掃描間隔，使用 `--max-attempts` 設定單一文件的 indexing retry 次數；indexing queue 儲存在 SQLite，重啟後可恢復未完成的 queue job。

`repair` 預設會修復失敗或未完成的 indexing，並報告孤立 vector；只有加上 `--prune-orphans` 才會刪除 metadata 不存在或已刪除文件的 vector。

`queue` 顯示 durable indexing jobs，可用 `--status` 篩選 queued、running、succeeded 或 failed。

The CLI uses the local Qwen embedding provider by default. KDB indexing uses
document summaries and chunk vectors only as indexes; precise answers read
content back from the original file. To enable KDB tools in TaskBrain, add:

```toml
[knowledge]
enabled = true
documents_root = "documents"
metadata = "data/knowledge/metadata.sqlite3"
vectors = "data/knowledge/vectors.lancedb"
embedding = "qwen3-embedding-0.6b"
embedding_device = "cpu"
```

When enabled, TaskBrain exposes `search_documents`, `search_in_document`,
`read_document`, `import_document`, and `create_document`. Agent-created or
imported files are written into the managed document root before indexing.

Mandarin transcripts normalize common ASCII punctuation to Chinese punctuation.

### Local Speaker Recognition

The first speaker-recognition backend uses SpeechBrain ECAPA-TDNN. It supports
multiple enrolled users and returns `unknown` when no enrolled profile reaches
the configured cosine-similarity threshold. Install it separately because the
model and PyTorch stack are optional:

```sh
uv sync --extra speaker
```

Enroll one user with several short, clean WAV recordings:

```sh
uv run --extra speaker myagent-speaker-enroll --user-id marvin
```

The interactive enrollment flow presents eight fixed Mandarin prompts one at a
time. It waits for VAD to detect speech, stops after trailing silence, checks
duration and volume, and retries invalid samples. Accepted recordings are held
in a temporary directory and removed after enrollment unless
`--keep-recordings` is specified. The final voiceprint is written only after
explicit confirmation. New users receive stable sequential IDs such as
`user-001`; display names remain profile data rather than system IDs. If a
voice cannot be matched, the runtime marks the turn as `unknown` and does not
read personal memory, profiles, tasks, or schedules. The fixed-file batch utility remains available as
`myagent-speaker-enroll-files`.

Enable recognition in the main agent:

```sh
uv run --extra speaker myagent --brain taskbrain \
  --speaker-recognition speechbrain \
  --speaker-profiles data/speaker/speaker_profiles.sqlite3
```

To test the current profiles interactively without starting the full agent:

```sh
uv run --extra speaker myagent-speaker-test
```

Speak one utterance at a time. The CLI automatically detects speech boundaries
and prints the best candidate, similarity score, current user, and identity
status. Use `Ctrl-C` to stop.

The current starting threshold is `0.35`; calibrate it using recordings from the real
microphone and room. Recognition compares against each enrolled sample and
uses the highest similarity score. Speaker recognition is an identity hint, not a secure
authentication mechanism, and raw enrollment audio is not stored by MyAgent. Recognition
runs in a single background worker so it does not block STT or the LLM. The runtime keeps
a `current_user` snapshot with hysteresis: scores below `0.20` become `unknown`, scores
from `0.20` up to `0.35` keep the previous user but are marked `ambiguous`, and scores
at or above `0.35` can identify or switch users. `ambiguous` and `unknown` turns cannot
read personal memory, profiles, tasks, or schedules. These are cosine similarity scores,
not calibrated statistical probabilities.

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

Run the main agent with `myagent.toml`. It remains alive until `Ctrl+C`:

```sh
./start
```

For a one-off override, pass a CLI flag. CLI values take precedence over the
configuration file:

```sh
./start --config myagent.toml --device 3 --wake-config wake.toml
```

Enable wake word gating with a sherpa-onnx KWS config. This is already enabled
by the example `myagent.toml`; the standalone override is:

```sh
uv run myagent --wake-config wake.toml
```

### macOS Location Helper

Build the optional native Core Location helper once:

```sh
./tools/build-location-helper.sh
```

The first time `get_location` is requested, macOS may ask for Location
Services permission. The helper returns latitude, longitude, accuracy, and a
timestamp. Configure its path in `myagent.toml`:

```toml
[environment]
location_helper = "tools/location_helper.app/Contents/MacOS/location_helper"
```

An explicitly configured `environment.location` takes precedence over the
helper. Location results are not written to long-term memory automatically.

### Environment Tools

TaskBrain exposes the following local environment tools to the model:

- `get_current_datetime`: the computer's local date and time is included in
  every turn automatically. The tool is used when a specific IANA timezone is
  requested, such as `Asia/Taipei` or `America/New_York`.
- `get_location`: returns the configured location or the optional macOS Core
  Location result.
- `get_ip_addresses`: returns `internal_ips` from local network interfaces and
  `external_ip` from the configured HTTPS endpoint. The legacy `ip` and
  `source` fields are also retained for compatibility.

If the external IP lookup fails, the tool still returns the internal IPs and
includes `external_error` so the model can report the failure and its reason.
IP and location results are not written to long-term memory automatically.

### Scheduled Tasks

TaskBrain can persist one-time and recurring task schedules in the configured
SQLite task database. The scheduling tools are `create_schedule`,
`list_schedules`, `pause_schedule`, `resume_schedule`, and `cancel_schedule`.
Use ISO-8601 `run_at` timestamps and optionally set `recurrence` to `daily` or
`weekly` with an IANA `timezone`. Due schedules create ordinary bounded tasks,
so they use the same registered worker types, task status, and notifications.
For spoken reminders, use the built-in `assistant_message` worker with the exact
spoken text in `input.message`; VoiceAgent delivers that notification at a safe
standby/TTS boundary.

For example, a one-time spoken reminder is represented as:

```json
{
  "title": "Say hello",
  "worker_type": "assistant_message",
  "run_at": "2026-09-20T15:30:00+08:00",
  "timezone": "Asia/Taipei",
  "input": {"message": "你好！"}
}
```

To test quickly, create a reminder for one or two minutes from now and wait
until the agent reaches standby. The schedule becomes `completed` when it has
triggered the underlying task; the task itself reports its own success or
failure. Existing schedules can be inspected with `list_schedules` and stopped
with `cancel_schedule`.

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
