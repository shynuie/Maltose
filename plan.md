# Development Plan

## Current Focus

Build a local TaskBrain behind the completed voice frontend. Use the OpenAI API as the initial model backend, while the primary runtime owns tool registration, LanceDB-backed semantic memory, and future MCP/skills adapters.

## Done

- Added local macOS TTS using `say`.
- Added `uv` project management.
- Added `myagent-tts` CLI entrypoint.
- Added basic TTS tests.
- Added local faster-whisper STT for audio files.
- Added `myagent-stt` CLI entrypoint.
- Added `myagent-listen` for microphone capture and VAD-based utterance files.
- Added a minimal listen-transcribe-speak voice loop.
- Added `VoiceAgent` with standby timeout, state machine, and `EchoBrain`.
- Added `myagent` and `myagent-run` CLI entrypoints with continuous and single-turn modes.
- Verified live voice interactions and timeout auto-shutdown with physical microphone.
- Added optional `WakeWordGate` abstraction and sherpa-onnx KWS config loading.
- Downloaded and configured sherpa-onnx KWS model locally.
- Added `myagent-wake-test` and `myagent-wake-monitor` CLI tools.
- Verified `麥芽糖` wake detection on Xiaomi microphone device 3.
- Verified `wake_detected -> VAD -> utterance wav -> Whisper STT` with `myagent-listen`.
- Added optional Fun-ASR-Nano STT provider and compared it against faster-whisper on five wake-command samples; Nano is currently better on the sample batch but remains experimental because it can retain or misrecognize wake-word audio.
- Added Qwen3-ASR-0.6B STT provider. It produced semantically correct commands on 5/5 English samples and 5/5 Chinese command intents; first model initialization is long.
- Switched the default STT provider to Qwen3-ASR-0.6B; faster-whisper and Fun-ASR-Nano remain selectable fallbacks.
- Added optional delayed `--wake-ack` short TTS acknowledgement after wake detection.
- Added `--wake-buffer-ms` ring buffer for one-shot wake commands; default is 1000 ms.
- Added STT model warmup at startup with a silent WAV and a spoken ready prompt after initialization.
- Qwen3-ASR-0.6B is now the default STT provider; alternatives remain selectable with `--stt-provider`.
- Added local English and Chinese command batches for STT comparison.
- Verified the complete wake -> VAD -> normalized audio -> Qwen3-ASR -> TTS path.
- All 49 unit tests pass.
- Added `OpenClawBrain` with Gateway HTTP client, bearer-token support, stable session id, and CLI selection.
- Added local `TaskBrain` with a tool registry, persistent JSON memory, and an OpenAI-compatible model adapter.
- Configured OpenAI API as the default model backend; local endpoints remain configurable.
- Added optional local Qwen3-Embedding-0.6B provider with cosine-similarity memory retrieval and keyword fallback.
- Added `--taskbrain-embedding` and `embeddings` dependency extra.
- Added `LanceMemoryStore` with persistent local vector storage and JSON migration.
- Added structured `user_profile` table support for stable identity data.
- Linked semantic memories to `user_profile.id` through `memories.user_id` and scoped recall by user.
- Added `vector-memory` dependency extra and memory backend CLI selection.
- Changed the conversation lifecycle to keep the process alive until `Ctrl+C`.
- Added active conversation sessions that accept follow-up speech without repeating the wake word; 10 seconds of silence returns to KWS standby.
- Added deterministic wake-only handling: a transcript containing only `麥芽糖`/`麦芽糖` replies `我在` without calling the LLM.
- Made the post-wake acknowledgement default to `我在` after the 0.8-second follow-up window.
- Added `return_to_standby` conversation-control tool for phrases such as `退下吧` and `沒事了`.
- Added pluggable `SpeakerIdentifier`, `SpeakerResult`, and `TurnContext` interfaces.
- Added parallel STT and speaker-identification workers for each completed utterance.
- Passed speaker-resolved `user_id` into TaskBrain and scoped memory/profile tools to that user.
- Added built-in `remember` and `recall` tools and a bounded tool execution loop.
- Added 49 unit tests covering the TaskBrain, memory, identity context, and voice flow.

## Architecture: Voice I/O + Agent Brain

Decouple the voice layer (Perception & Expression) from the reasoning layer (Brain & Workflow):

```text
User Speech -> Mic/VAD (Ear) -> STT -> [ AgentBrain Protocol ] -> TTS (Mouth) -> User
                                              │
                                              ▼
                                 Local TaskBrain
                         (Tools, Memory, MCP/Skills Adapters)
                                      │
                         OpenAI-compatible Task Model
```

MyAgent serves as the local voice interface (Ears & Mouth / Voice Channel) for the personal assistant.

## Roadmap & Phases

### Phase 1: Minimal Standby Voice Agent (Done)
- Built a standalone `VoiceAgent` with lifecycle and timeout handling.
- Implemented `AgentBrain` protocol with `EchoBrain`.
- Implemented standby timeout ($t$ seconds) and clean auto-shutdown.
- Added single-turn and continuous standby modes (`--continuous`).
- Added CLI entrypoints `myagent` and `myagent-run`.
- Verified live mic input and 20 passing unit tests.

### Phase 2: Local TaskBrain (In Progress)
Keep the agent orchestration in MyAgent so the voice workflow does not depend on a separate agent runtime:
- **TaskBrain core**: local tool registry, persistent memory, model adapter, and bounded tool loop.
- **Memory retrieval**: use Qwen3 Embedding with LanceDB cosine search; retain JSON/keyword storage as a fallback and migration source.
- **User profile**: keep identity and stable preferences in a structured table, separate from semantic memory.
- **Speaker identity**: resolve a speaker embedding to `user_id` before TaskBrain memory access.
- **Database schema**:

```text
user_profile
├── id                 # stable user_id
├── display_name
├── full_name
└── chinese_name

speaker_profiles
├── id
├── user_id             # FK-like link to user_profile.id
├── embedding_model
└── created_at

memories
├── id
├── user_id             # FK-like link to user_profile.id
├── text
├── tags
├── embedding
└── created_at
```

- **Voice turn flow**:

```text
KWS wake_detected
    -> VAD captures command utterance
    -> STT worker          (parallel A)
    -> Speaker worker      (parallel B)
    -> TurnContext(user_id, speaker_score, speaker_status)
    -> TaskBrain / user-scoped tools
```

- **Current status**:
  - Implemented `TaskBrain`, `ToolRegistry`, `MemoryStore`, and `OpenAICompatibleTaskModel`.
  - Added `remember` and `recall` built-in tools.
  - Added `--brain taskbrain` and local JSON memory configuration.
  - Installed the vector-memory extra and verified LanceDB migration/search with 49 tests.
  - Implemented the speaker identification framework; concrete speaker model and enrollment flow remain.
  - Remaining: run the live LanceDB voice smoke test, then add a concrete local speaker model.
- **Next**: add MCP client and skills loader adapters that expose capabilities through `ToolRegistry`.
- **Conversation lifecycle**: one wake starts a session; silence timeout ends the session but never exits the process.

### Phase 2b: Optional OpenClaw Integration
OpenClaw remains available when its broader runtime is useful, but is not required by MyAgent:
- **OpenClaw Setup**: Local installation via `brew install openclaw-cli` or `npm install -g openclaw`.
- **OpenClaw Gateway**: Runs on default port `18789` (`openclaw gateway`).
- **Implement `OpenClawBrain`**:
  - Connect to local OpenClaw Gateway via OpenAI-compatible HTTP API (`POST http://localhost:18789/v1/chat/completions`) or WebSocket (`ws://localhost:18789`).
  - Flow:
    1. STT produces transcript.
    2. Send transcript as user message to OpenClaw Gateway.
    3. OpenClaw handles reasoning, tool execution (Shell, browser, files), and long-term memory.
    4. OpenClaw response text is returned to MyAgent.
    5. MyAgent speaks the response via local TTS.
  - **Current status**:
  - Implemented the Python Gateway client and `--brain openclaw` CLI path.
  - Remaining: configure a local OpenClaw Gateway and run an optional end-to-end voice smoke test.

### Phase 3: Streaming Keyword / Wake Word Mode (Done: Usable First Pass)
Support hands-free background listening activated only when a keyword is spoken:
- **Primary approach: sherpa-onnx KWS WakeWordGate**:
  - Keep the microphone stream open and process short PCM frames continuously.
  - Do not continuously write audio files for wake detection.
  - Use sherpa-onnx KWS to emit `wake_detected` before the existing VAD utterance capture starts.
  - Store wake configuration in a TOML file, including model paths, token file, tokenized `keywords_file`, threshold, score, provider, and thread count.
- **Fallback approach: transcript-based keyword matching**:
  - Keep as a secondary/fallback mode because it requires no KWS model.
  - Use only after VAD/STT, so it is less efficient and more exposed to Whisper hallucinations.
- **Initial interaction flow: two-stage wake**:
  - "麥芽糖" -> `wake_detected` -> wait briefly for follow-up speech.
  - If speech starts before `--wake-ack-delay`, prepend the wake ring buffer and process the command directly.
  - If no speech starts before the delay, optionally acknowledge ("我在") and keep listening for the follow-up command.
- **Later interaction flow: one-shot wake**:
  - "小助手，今天天氣如何？" -> preserve a short ring buffer around the wake event, strip or ignore the wake phrase, process the remaining command.
- **Background conversation**:
  - If KWS does not detect the keyword, audio never reaches Whisper.

### Phase 4: Voice Pipeline Enhancements (Next)
- **Whisper Hallucination Mitigation**:
  - Filter out very short utterances (< 1.2s) or configure Whisper `no_speech_threshold` to avoid subtitle artifacts (e.g. "字幕by索兰娅").
- **Interruptible TTS**:
  - Allow `speech_started` to immediately halt ongoing TTS speech before STT completes.
- **Audio Cues**:
  - Short audio tones for standby ready, wake word recognized, and auto-shutdown.
- **Streaming STT**:
  - Real-time partial transcript streaming.

## Current Voice Flows

Implemented flows:

```text
text -> TTS provider -> speech/audio file
audio file -> STT provider -> text output
mic audio -> VAD -> utterance audio file
mic audio -> VAD -> STT -> TTS echo reply
mic audio -> VAD -> standby timeout -> auto shutdown
mic audio -> KWS WakeWordGate -> wake_detected -> VAD -> utterance audio file
```

Optional listening transcription:

```text
mic audio -> VAD -> utterance audio file -> STT provider -> text output
```

## Listening Model

Use an event-driven listening loop:

```text
standby
-> speech_started
-> collect audio frames
-> speech_ended after enough silence
-> finalize utterance
-> send utterance to STT queue
-> return to standby
```

`speech_started` should eventually be able to interrupt current TTS or agent output before STT finishes. Interruption should not wait for transcription.

## VAD Plan

Start with WebRTC VAD for the first live listening implementation.

- Keep it local and lightweight.
- Use 16 kHz mono PCM audio.
- Process short frames, likely 20 ms.
- Use pre-roll audio so the first syllable is not clipped.
- Treat a silence window as utterance end.

Initial tuning values:

```text
frame_ms = 20
sample_rate = 16000
vad_aggressiveness = 2
start_trigger_ms = 160
end_silence_ms = 700
pre_roll_ms = 300
```

These values are starting points. Mandarin speech may need a slightly longer end silence threshold because short pauses are common.
