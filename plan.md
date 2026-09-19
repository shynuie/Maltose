# Development Plan

## Current Focus

Connect the completed local voice frontend directly to OpenClaw ("龍蝦") as the backend brain via its Gateway API. The next application-level concern is converting imperfect STT text into constrained intents before tool execution.

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
- All 34 unit tests pass.

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
