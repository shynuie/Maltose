# Development Plan

## Current Focus

Connect the MyAgent voice frontend (ears and mouth) directly to OpenClaw ("龍蝦") as the backend brain via its Gateway API, while planning keyword wake word mode and STT hallucination filtering.

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

## Architecture: Voice I/O + Agent Brain

Decouple the voice layer (Perception & Expression) from the reasoning layer (Brain & Workflow):

```text
User Speech -> Mic/VAD (Ear) -> STT -> [ AgentBrain Protocol ] -> TTS (Mouth) -> User
                                              │
                                              ▼
                                 Direct Target: OpenClaw Gateway
                                 (Local-first Agent Brain, Tools & Memory)
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

### Phase 2: Direct OpenClaw ("龍蝦") Integration (Next)
Skip building custom scratch agent workflows or intermediate tool frameworks. Connect MyAgent directly to OpenClaw:
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

### Phase 3: Keyword / Wake Word Mode
Support hands-free background listening activated only when a keyword is spoken:
- **Transcript-based Keyword Matching**:
  - Zero extra acoustic dependencies; supports arbitrary Mandarin/English keywords (e.g. `--keyword "小助手"`, `--keyword "龍蝦"`).
- **Interaction Flows**:
  - *One-shot*: "小助手，今天天氣如何？" -> Strips keyword, processes "今天天氣如何？".
  - *Two-stage*: "小助手" -> Speaks acknowledgement ("我在") -> Enters standby listening for follow-up command.
  - *Background conversation*: If the keyword is absent, the utterance is silently ignored.

### Phase 4: Voice Pipeline Enhancements
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
