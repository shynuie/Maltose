# Development Plan

## Current Focus

Build the voice system first, starting with simple text-to-speech and speech-to-text workflows.

## Done

- Added local macOS TTS using `say`.
- Added `uv` project management.
- Added `myagent-tts` CLI entrypoint.
- Added basic TTS tests.
- Added local faster-whisper STT for audio files.
- Added `myagent-stt` CLI entrypoint.
- Added `myagent-listen` for microphone capture and VAD-based utterance files.
- Added a minimal listen-transcribe-speak voice loop.

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

## Listening Milestones

1. Done: Add microphone capture dependencies and a small audio input module.
2. Done: Add a VAD-based utterance segmenter.
3. Done: Add a listening CLI:

   ```sh
   uv run myagent-listen
   ```

4. Done: Save each finalized utterance as a WAV file:

   ```sh
   recordings/utterance-001.wav
   ```

5. Done: Print listening events:

   ```text
   listening...
   speech_started
   speech_ended recordings/utterance-001.wav duration=2.4s
   ```

6. Done: Add optional STT after utterance finalization:

   ```sh
   uv run myagent-listen --transcribe
   ```

7. Next: Test with real Mandarin speech and tune VAD thresholds.
8. Next: Add interruption events:

   ```text
   speech_started -> interrupt current TTS
   ```

## STT Provider

Use faster-whisper for the first STT implementation.

- Better privacy and offline support.
- More stable once installed because runtime does not depend on a remote API.
- Requires local model management and a little more setup.
- Start with the multilingual `small` model and Mandarin language hint `zh`.
- Upgrade the model only if accuracy is not good enough.

## Near-Term Recommendation

Test `myagent-listen` with real Mandarin speech and tune the VAD thresholds before coupling it tightly to agent behavior.

OpenAI Whisper API can remain a future fallback, but it is not the default path.

## Later

- Streaming STT.
- Wake word support.
- Interruptible TTS.
- Full voice loop:

  ```text
  listen -> transcribe -> think -> speak
  ```
