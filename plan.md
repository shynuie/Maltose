# Development Plan

## Current Focus

Build the Main Agent core by connecting the voice system (ears and mouth) to a lifecycle-controlled agent, with direct integration to OpenClaw ("龍蝦") as the backend brain.

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
Build a minimal, standalone `VoiceAgent` focused on lifecycle and timeout handling:
- **Standby Timeout ($t$ seconds)**:
  - Agent starts in standby.
  - If no speech is detected within $t$ seconds, cleanly shuts down.
  - If speech is detected within $t$ seconds, pauses timeout, completes utterance, transcribes, and replies.
- **Abstract `AgentBrain`**:
  - Implement a clean `AgentBrain` protocol.
  - Use `EchoBrain` / minimal responder for Phase 1 to verify the audio pipeline and lifecycle.
- **State Machine**:
  `STANDBY` -> `LISTENING` -> `THINKING` -> `SPEAKING` -> `SHUTDOWN` (or return to `STANDBY`).
- **CLI Entrypoint**:
  CLI command to run the agent with configurable standby timeout (e.g. `uv run myagent-run --timeout 10`).

### Phase 2: Direct OpenClaw ("龍蝦") Integration (Next)
Skip building custom scratch agent workflows or intermediate tool frameworks. Connect MyAgent directly to OpenClaw:
- Implement `OpenClawBrain` connecting to the local OpenClaw Gateway (via WebSocket / HTTP API).
- Flow:
  1. STT produces transcript.
  2. Send transcript as user message to OpenClaw Gateway.
  3. OpenClaw handles reasoning, tool execution (Shell, browser, files), and long-term memory.
  4. OpenClaw response text is streamed/returned to MyAgent.
  5. MyAgent speaks the response via local TTS.

## Current Voice Flows

Implemented flows:

```text
text -> TTS provider -> speech/audio file
audio file -> STT provider -> text output
mic audio -> VAD -> utterance audio file
mic audio -> VAD -> STT -> TTS echo reply
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

## Later Enhancements

- Streaming STT.
- Wake word support.
- Interruptible TTS (stop speaking immediately when user speaks).
- Audio cues (short sound on standby ready / timeout shutdown).
