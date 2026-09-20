# Development Plan

## Current Focus

Continue the local multi-task orchestration layer behind TaskBrain while completing the streaming voice path. Planner execution, durable task state, short-term session memory, completion summaries, and throttled progress notifications are working. The next focus is the local multi-user speaker enrollment/identification flow, followed by MCP/Skills integration and durable task recovery.

## Status At A Glance

### Completed

- Always-on voice loop with KWS wake word, VAD, Qwen3-ASR-0.6B STT, normalization, and macOS TTS.
- Wake-only acknowledgement, 10-second conversation timeout, explicit return-to-standby control, and cancellable barge-in TTS.
- Bounded in-memory conversation sessions. Context is retained between wake and standby, then cleared without entering long-term memory.
- TaskBrain with OpenAI-compatible model access, bounded tool loop, and tools for memory, profile, tasks, standby control, and web search.
- LanceDB vector memory with local Qwen3-Embedding-0.6B and user-scoped memories.
- Structured `user_profile` storage linked to memories through `user_id`.
- Explicit microphone trust remains available only through `--taskbrain-trust-user-id`.
- Brave web search and bounded multi-query `web_research` worker.
- Initial Planner behavior through `create_task_plan`: the model can turn a request into a bounded task DAG.
- SQLite task store, dependency-aware scheduling, bounded parallel workers, status queries, cancellation, retry, and read-only Codex worker.
- Runtime task completion/failure notifications scoped by user and announced at a safe TTS boundary.
- LLM-generated concise summaries for completed task results, plus throttled 25/50/75% progress notifications.
- Planner safety boundaries: plans are capped at 8 tasks; ambiguous requests require clarification, and side-effecting work requires confirmation.
- Added `list_active_tasks` so the model can query pending, running, and waiting work directly.
- Added a capability adapter boundary for explicitly registered Skills and MCP tools, plus a stdio JSON-RPC MCP client, TOML Skills manifest loader, and `--taskbrain-mcp-command` CLI integration.
- Added unified `myagent.toml` configuration with CLI override support; local config is ignored by Git and `myagent.toml.example` documents the available sections.
- Added built-in `get_current_datetime`, `get_location`, and `get_ip_addresses` tools with config support and privacy boundaries.
- Added persisted one-time and daily/weekly scheduled tasks with timezone-aware timestamps, pause/resume/cancel controls, and TaskBrain scheduling tools.
- Added the `assistant_message` worker so scheduled spoken reminders are delivered through the existing VoiceAgent notification path at a safe TTS boundary.
- Added the first streaming LLM-to-TTS slice: OpenAI-compatible SSE output is split at sentence punctuation while preserving terminal punctuation.
- Added background LLM stream buffering so model generation can continue while completed speech segments are played.
- Added the first local speaker identity slice: SpeechBrain ECAPA-TDNN adapter, multi-user SQLite voiceprint enrollment, cosine matching, and explicit `unknown` rejection.
- Added an interactive speaker-enrollment CLI with fixed prompts, VAD start/end detection, duration/volume validation, retries, confirmation, and temporary raw-audio cleanup.
- Assigned new system identities with stable sequential `user-NNN` IDs; names remain separate profile data.
- Enabled speaker recognition by default; unmatched or failed recognition stays `unknown` and cannot access personal data.
- Speaker profiles now retain individual enrollment embeddings and identify using the highest sample similarity.
- Added an asynchronous `SpeakerIdentityManager` with a current-user snapshot and hysteresis (`<0.20` unknown, `0.20–<0.40` ambiguous/hold, `>=0.40` identified) so speaker recognition does not block STT or LLM processing.
- Enforced the privacy boundary for both `unknown` and `ambiguous` states; only an `identified` turn may access personal memory, profile, task, or schedule data.
- 84 automated tests covering voice flow, streaming sentence delivery, memory, identity, tasks, schedules, search, STT, TTS, capability adapters, and configuration loading.

### In Progress

- Add MCP reconnect handling and expose configured Skills manifests through the CLI.
- Durable task recovery and notification replay after process restart.
- Require explicit confirmation for schedules that trigger external side effects.
- Reconnect streaming LLM, TTS, and listener execution with explicit events/queues so streaming replies support barge-in without blocking or generator races.
- Calibrate speaker thresholds with real microphone recordings and complete live VoiceAgent speaker-recognition validation; the current starting threshold is 0.40. The asynchronous identity manager is implemented, but first-turn warm-up and live multi-speaker switching still need validation.

### Not Started / Later

- MCP reconnect handling and skill-to-worker registration.
- Write-capable Codex worker with explicit confirmation and `workspace-write` sandboxing.
- Full-page web extraction and source-aware research synthesis.
- Streaming STT and production hardening for the streaming LLM/TTS sentence queue.
- Persistent task recovery and notification replay after process restart.

## Planned Built-in Environment Features

These capabilities should be implemented as narrow, auditable tools rather than unrestricted shell access.

- **Scheduled tasks** (initial slice implemented; confirmation policy remains):
  - Support one-time and recurring schedules with timezone-aware timestamps.
  - Persist schedules in SQLite and restore them after process restart.
  - Add tools to create, list, pause, resume, and cancel schedules.
  - Require confirmation for schedules that trigger external side effects.
  - Spoken reminders use the `assistant_message` worker and preserve the exact `input.message` text.
- **Date and time** (implemented):
  - Add a deterministic local `get_current_datetime` tool.
  - Return timezone, ISO-8601 timestamp, local date, local time, and weekday.
  - Use the configured system timezone by default and allow an explicit timezone query.
- **Location** (implemented with manual configuration and macOS helper):
  - Add a `get_location` tool with explicit source reporting.
  - Support manually configured location first and an optional permission-controlled macOS Core Location helper.
  - Do not silently infer or persist location without user consent.
- **External IP** (implemented):
  - Add a bounded `get_ip_addresses` tool using a configured or allowlisted HTTPS endpoint.
  - Clearly distinguish local/private IP from public/external IP.
  - Treat the result as sensitive network metadata and do not store it in long-term memory by default.
- **Speaker identity** (framework implemented; concrete model planned):
  - Start with SpeechBrain ECAPA-TDNN for local speaker embeddings and keep it behind a `SpeakerEmbeddingAdapter` so the backend can later be replaced by 3D-Speaker or an ONNX model.
  - Support enrollment of multiple known users, with several short recordings per user and an averaged/normalized voiceprint.
  - Compare each completed utterance against all enrolled profiles and return the best match only when it passes a locally calibrated similarity threshold.
  - Return `unknown` when no profile passes the threshold; never silently map an unrecognized speaker to `default`.
  - Store embeddings and model metadata in `speaker_profiles`; avoid storing raw enrollment audio by default.
  - Keep speaker verification separate from diarization and treat it as an identity hint, not high-security authentication.

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
- The full test suite currently has 69 passing tests.
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
- Committed the current prototype as `9445bf5` (`Build local TaskBrain prototype`).
- Added pluggable `SpeakerIdentifier`, `SpeakerResult`, and `TurnContext` interfaces.
- Added parallel STT and speaker-identification workers for each completed utterance.
- Passed speaker-resolved `user_id` into TaskBrain and scoped memory/profile tools to that user.
- Added built-in `remember` and `recall` tools and a bounded tool execution loop.
- Added unit tests covering the TaskBrain, memory, identity context, and voice flow.
- Added the first local multi-task slice: SQLite `TaskStore`, durable task lifecycle, dependency-aware `TaskManager`, bounded worker pool, and TaskBrain task-management tools.
- Added task tests covering persistence, parallel execution, dependencies, cancellation/retry, user scoping, and safe handling of unregistered worker types.
- Added a read-only `CodexReadOnlyWorker` using `codex exec --sandbox read-only`, with bounded runtime, output limits, ephemeral sessions, and safe failure handling.
- Added the web-search design: provider abstraction for quick searches now, with a separate multi-page research worker planned later.
- Added `WebSearchProvider`, Brave Search integration, and the optional TaskBrain `web_search` tool with bounded results, timeout, source URLs, and freshness filters.
- Added a bounded `WebResearchWorker` that runs multiple searches, deduplicates source URLs, reports progress, and returns a capped structured result for later LLM summarization.
- Added runtime task completion notifications scoped by `user_id`; completed or failed tasks can now be announced by VoiceAgent at a safe TTS boundary without interrupting active speech.
- Made macOS `say` single-flight and cancellable; VoiceAgent now captures barge-in speech during replies, asks TaskBrain whether it explicitly requests interruption, stops the active speech process only for a positive decision, and queues the utterance for STT/LLM processing.
- Closed the unknown-speaker memory boundary: unverified turns no longer fall back to `default` and cannot access personal memory, profile, or task state; explicit microphone trust is opt-in.
- Until a concrete speaker model is installed, CLI microphone turns explicitly trust `--taskbrain-user-id` as the temporary active user; future speaker identification will override this fallback.
- Added bounded in-memory short-term conversation sessions. A session starts at wake detection, retains follow-up turns until silence or explicit standby, and is cleared without writing dialogue into long-term memory.

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
    -> Speaker identity worker (parallel B, single background queue)
    -> current_user snapshot / hysteresis state
    -> TurnContext(user_id, speaker_score, speaker_status)
    -> TaskBrain / user-scoped tools
```

- **Current status**:
  - Implemented `TaskBrain`, `ToolRegistry`, `MemoryStore`, and `OpenAICompatibleTaskModel`.
  - Added `remember` and `recall` built-in tools.
  - Added `--brain taskbrain` and local JSON memory configuration.
  - Installed the vector-memory extra and verified LanceDB migration/search with 49 tests.
  - Implemented the speaker identification framework; concrete speaker model and enrollment flow remain.
  - Remaining: calibrate thresholds with local recordings, validate model performance on the microphone path, and add user-profile enrollment UX if needed.
- **Next**: expose configured MCP and Skills adapters through the CLI, then connect selected capabilities to TaskManager workers.
- **Conversation lifecycle**: one wake starts a session; silence timeout ends the session but never exits the process.
- **Short-term conversation memory**: TaskBrain retains bounded user, assistant, and tool messages within the active session. The default cap is 12 turns, and the history is discarded on standby or process shutdown to control token usage and prevent cross-session leakage.

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
  - Capture barge-in audio, run STT and an explicit YES/NO interruption classifier, then halt ongoing TTS only for a positive decision. (Implemented first pass for macOS `say`; broader audio echo control remains.)
- **Audio Cues**:
  - Short audio tones for standby ready, wake word recognized, and auto-shutdown.
- **Streaming STT**:
  - Real-time partial transcript streaming.

### Phase 5: Multi-task Agent Orchestration (In Progress)

Build a bounded local task system rather than a fully distributed multi-agent runtime.

**Implementation status:** Initial planning, durable task state, bounded execution, completion/progress notification, and LLM result summarization slices are implemented. The current version persists plans, supports registered Python workers, includes a read-only Codex worker, and can optionally expose Brave web search plus bounded multi-query research to TaskBrain. Full page extraction, MCP, Skills, and write-capable workers are not connected yet.

- **Task request**:
  - Convert one user command into a structured task plan.
  - Ask for confirmation when the plan includes file changes, external side effects, or destructive actions.
  - Give an immediate concise acknowledgement describing the planned work.
  - Current implementation caps plans at 8 tasks and prompts the model to clarify ambiguous requests or request confirmation before side effects.
- **Task graph**:
  - Represent tasks as a DAG with `task_id`, `parent_task_id`, dependencies, worker type, status, progress, result summary, error, timestamps, and `user_id`.
  - Run independent tasks concurrently; serialize dependent tasks.
  - Start with a local SQLite task store. Do not use the vector memory database for active task state.
- **Task lifecycle**:
  - `pending -> running -> waiting -> succeeded | failed | cancelled`.
  - Support status queries, cancellation, retry, and final result aggregation.
  - Keep task state durable across a process restart.
- **Worker model**:
  - Add a `TaskWorker` protocol and bounded worker pool, initially limited to 2-3 concurrent tasks.
  - Implement read-only Codex worker first through `codex exec --sandbox read-only`.
  - Add a separate write-capable Codex worker only behind explicit user confirmation and `workspace-write` sandboxing.
  - Later adapt MCP tools and skills into workers without coupling them to the voice layer.
- **Web search**:
  - Add a `WebSearchProvider` protocol and a provider adapter with explicit timeout, result-count, and response-size limits.
  - Expose `web_search` to TaskBrain for short current-information queries.
  - Preserve title, URL, snippet, and publication metadata so responses can cite sources.
  - Treat search content as untrusted data and never allow it to override agent instructions or directly trigger side effects.
  - `web_research` worker is implemented for bounded multi-query research; full-page extraction and source-aware synthesis remain future work.
- **Progress and notification**:
  - Track progress from deterministic worker events, process output, and task state rather than polling the LLM every few seconds.
  - Do not announce short tasks; announce long-running tasks after an initial threshold and then at a bounded interval.
  - Never interrupt active user speech; queue notifications for a safe TTS point.
  - Let the user ask for status, cancel a task, or request a concise final summary.
  - Current slice: announce throttled progress and task success/failure at a safe TTS boundary, with a bounded LLM summary for completed results.
- **Token and safety budgets**:
  - Use one planner call per user request and send each worker only its scoped context.
  - Re-plan only after a worker failure or a dependency result that requires a decision.
  - Bound task count, worker runtime, retries, output size, and total planner/tool rounds.
  - Redact secrets from worker logs and never pass arbitrary shell commands directly from voice input.
- **Initial tools**:
  - `create_task_plan`
  - `get_task_status`
  - `list_tasks`
  - `list_active_tasks`
  - `cancel_task`
  - `retry_task`
  - `return_to_standby`

Initial target flow:

```text
Voice command
    -> STT + speaker identity
    -> TaskBrain planner
    -> TaskManager persists task DAG
    -> bounded worker pool executes independent tasks
    -> event-driven progress notifications
    -> TaskBrain summarizes final results
    -> TTS response
```

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
