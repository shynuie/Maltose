from __future__ import annotations

import logging
from datetime import datetime
from enum import Enum
from pathlib import Path
from typing import Callable, Iterator, Protocol

from myagent.agent.brain import AgentBrain, EchoBrain
from myagent.agent.config import AgentConfig
from myagent.voice import (
    FasterWhisperSTT,
    ListeningEvent,
    MacOSSayTTS,
    STTRequest,
    STTResult,
    TTSRequest,
    VADSettings,
    write_utterance_wav,
)
from myagent.voice.listening import microphone_events

logger = logging.getLogger(__name__)


class AgentState(str, Enum):
    INITIALIZING = "initializing"
    STANDBY = "standby"
    LISTENING = "listening"
    THINKING = "thinking"
    SPEAKING = "speaking"
    SHUTDOWN = "shutdown"


class STTProvider(Protocol):
    def transcribe(self, request: STTRequest) -> STTResult:
        ...


class TTSProvider(Protocol):
    def synthesize(self, request: TTSRequest) -> None:
        ...


ListenerFactory = Callable[
    [VADSettings, str | int | None, float | None],
    Iterator[ListeningEvent],
]


class VoiceAgent:
    """Main Voice Agent controlling standby, listening, thinking, and speaking."""

    def __init__(
        self,
        config: AgentConfig | None = None,
        brain: AgentBrain | None = None,
        transcriber: STTProvider | None = None,
        speaker: TTSProvider | None = None,
        listener_factory: ListenerFactory = microphone_events,
    ) -> None:
        self.config = config or AgentConfig()
        self.brain = brain or EchoBrain()
        self._transcriber = transcriber
        self._speaker = speaker
        self._listener_factory = listener_factory
        self.state = AgentState.INITIALIZING
        self.turn_count = 0

    @property
    def transcriber(self) -> STTProvider:
        if self._transcriber is None:
            self._transcriber = FasterWhisperSTT()
        return self._transcriber

    @property
    def speaker(self) -> TTSProvider:
        if self._speaker is None:
            self._speaker = MacOSSayTTS()
        return self._speaker

    def run(self) -> None:
        logger.info(
            "agent_starting timeout=%.1fs continuous=%s",
            self.config.standby_timeout,
            self.config.continuous,
        )

        try:
            while self.state != AgentState.SHUTDOWN:
                self.state = AgentState.STANDBY
                logger.info("agent_standby timeout=%.1fs", self.config.standby_timeout)

                captured_utterance = None
                for event in self._listener_factory(
                    self.config.vad_settings,
                    self.config.device,
                    self.config.standby_timeout,
                ):
                    if event.kind == "standby_timeout":
                        logger.info("agent_standby_timeout reached, shutting down")
                        self.state = AgentState.SHUTDOWN
                        break
                    elif event.kind == "speech_started":
                        self.state = AgentState.LISTENING
                        logger.info("speech_started")
                    elif event.kind == "speech_ended" and event.utterance is not None:
                        captured_utterance = event.utterance
                        logger.info(
                            "speech_ended duration=%.2fs",
                            captured_utterance.duration_seconds,
                        )
                        break

                if self.state == AgentState.SHUTDOWN or captured_utterance is None:
                    break

                self.turn_count += 1
                self.state = AgentState.THINKING

                path = _next_output_path(self.config.output_dir, self.turn_count)
                write_utterance_wav(path, captured_utterance)

                logger.info("transcribing audio_path=%s", path)
                result = self.transcriber.transcribe(
                    STTRequest(
                        audio_path=path,
                        model_size=self.config.whisper_model,
                        language=self.config.whisper_language,
                        compute_type=self.config.whisper_compute_type,
                    )
                )
                logger.info("transcript text=%s", result.text)

                if not result.text.strip():
                    logger.info("empty_transcript_ignored")
                    if not self.config.continuous:
                        self.state = AgentState.SHUTDOWN
                        break
                    continue

                reply_text = self.brain.process(result.text)
                logger.info("brain_reply text=%s", reply_text)

                self.state = AgentState.SPEAKING
                logger.info("speaking text=%s", reply_text)
                self.speaker.synthesize(
                    TTSRequest(
                        text=reply_text,
                        voice=self.config.tts_voice,
                        rate=self.config.tts_rate,
                    )
                )
                logger.info("speaking_done")

                if not self.config.continuous:
                    logger.info("single_turn_complete, shutting down")
                    self.state = AgentState.SHUTDOWN
                    break

                if (
                    self.config.max_turns is not None
                    and self.turn_count >= self.config.max_turns
                ):
                    logger.info(
                        "max_turns reached (%d), shutting down", self.turn_count
                    )
                    self.state = AgentState.SHUTDOWN
                    break

        except KeyboardInterrupt:
            logger.info("agent_interrupted")
            self.state = AgentState.SHUTDOWN
        finally:
            self.state = AgentState.SHUTDOWN
            logger.info("agent_stopped")


def _next_output_path(output_dir: Path, turn_count: int) -> Path:
    stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    return output_dir / f"agent-turn-{turn_count:03d}-{stamp}.wav"
