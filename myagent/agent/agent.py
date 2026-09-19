from __future__ import annotations

import logging
import re
import tempfile
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime
from dataclasses import dataclass
from enum import Enum
from pathlib import Path
from typing import Callable, Iterator, Protocol

from myagent.agent.brain import AgentBrain, EchoBrain, TurnContext
from myagent.agent.config import AgentConfig
from myagent.voice import (
    FasterWhisperSTT,
    ListeningEvent,
    MacOSSayTTS,
    STTRequest,
    STTResult,
    TTSRequest,
    Utterance,
    VADSettings,
    WakeWordDetector,
    measure_utterance,
    normalize_utterance_peak,
    NullSpeakerIdentifier,
    SpeakerIdentifier,
    SpeakerResult,
    create_stt_provider,
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


@dataclass(frozen=True)
class PendingTurn:
    utterance: Utterance
    transcript: str
    speaker_result: SpeakerResult


ListenerFactory = Callable[
    [VADSettings, str | int | None, float | None, WakeWordDetector | None, float, int],
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
        speaker_identifier: SpeakerIdentifier | None = None,
        listener_factory: ListenerFactory = microphone_events,
    ) -> None:
        self.config = config or AgentConfig()
        self.brain = brain or EchoBrain()
        self._transcriber = transcriber
        self._speaker = speaker
        self._speaker_identifier = speaker_identifier or NullSpeakerIdentifier()
        self._listener_factory = listener_factory
        self.state = AgentState.INITIALIZING
        self.turn_count = 0

    @property
    def transcriber(self) -> STTProvider:
        if self._transcriber is None:
            self._transcriber = create_stt_provider(
                provider=self.config.stt_provider,
                model=self.config.whisper_model,
                device=self.config.stt_device,
                compute_type=self.config.whisper_compute_type,
            )
        return self._transcriber

    @property
    def speaker(self) -> TTSProvider:
        if self._speaker is None:
            self._speaker = MacOSSayTTS()
        return self._speaker

    def run(self) -> None:
        logger.info(
            "agent_starting conversation_timeout=%.1fs",
            self.config.standby_timeout,
        )

        try:
            self._warm_up_transcriber()
            conversation_active = self.config.wake_word_detector is None
            if conversation_active:
                self._begin_brain_session()
            pending_turn: PendingTurn | None = None
            while self.state != AgentState.SHUTDOWN:
                self.state = AgentState.STANDBY
                logger.info(
                    "agent_standby wake_required=%s conversation_timeout=%s",
                    not conversation_active,
                    self.config.standby_timeout if conversation_active else "disabled",
                )

                captured_utterance = pending_turn.utterance if pending_turn else None
                pretranscribed_turn = pending_turn
                pending_turn = None
                if captured_utterance is None:
                    for event in self._listener_factory(
                        self.config.vad_settings,
                        self.config.device,
                        self.config.standby_timeout if conversation_active else None,
                        None if conversation_active else self.config.wake_word_detector,
                        self.config.wake_ack_delay,
                        self.config.wake_buffer_ms,
                    ):
                        if event.kind == "standby_timeout":
                            logger.info("conversation_silence_timeout returning_to_standby")
                            self._end_brain_session()
                            conversation_active = self.config.wake_word_detector is None
                            break
                        elif event.kind == "speech_started":
                            self.state = AgentState.LISTENING
                            logger.info("speech_started")
                        elif event.kind == "wake_detected":
                            logger.info("wake_detected keyword=%s", event.keyword)
                            self._begin_brain_session()
                        elif event.kind == "wake_ack_requested":
                            self._speak_wake_ack()
                        elif event.kind == "speech_ended" and event.utterance is not None:
                            captured_utterance = event.utterance
                            conversation_active = True
                            logger.info(
                                "speech_ended duration=%.2fs",
                                captured_utterance.duration_seconds,
                            )
                            break

                if self.state == AgentState.SHUTDOWN:
                    break
                if captured_utterance is None:
                    continue

                self.turn_count += 1
                self.state = AgentState.THINKING

                path = _next_output_path(self.config.output_dir, self.turn_count)
                stt_utterance = self._prepare_stt_utterance(captured_utterance)
                write_utterance_wav(path, stt_utterance)

                if pretranscribed_turn is not None:
                    result = STTResult(
                        text=pretranscribed_turn.transcript,
                        language=self.config.whisper_language,
                        duration=captured_utterance.duration_seconds,
                        segments=[],
                    )
                    speaker_result = pretranscribed_turn.speaker_result
                    logger.info("using_pretranscribed_barge_in")
                else:
                    logger.info("transcribing audio_path=%s", path)
                    stt_request = STTRequest(
                        audio_path=path,
                        model_size=self.config.whisper_model,
                        language=self.config.whisper_language,
                        compute_type=self.config.whisper_compute_type,
                    )
                    with ThreadPoolExecutor(max_workers=2) as executor:
                        stt_future = executor.submit(self.transcriber.transcribe, stt_request)
                        speaker_future = executor.submit(self._speaker_identifier.identify, path)
                        result = stt_future.result()
                        speaker_result = speaker_future.result()
                logger.info("transcript text=%s", result.text)
                logger.info(
                    "speaker_result user_id=%s score=%s status=%s",
                    speaker_result.user_id,
                    speaker_result.score,
                    speaker_result.status,
                )

                if not result.text.strip():
                    logger.info("empty_transcript_ignored")
                    continue

                if _is_wake_only(result.text, self.config.wake_keywords):
                    reply_text = self.config.wake_ack_text or "我在"
                    logger.info("wake_only_reply text=%s", reply_text)
                else:
                    reply_text = self.brain.process(
                        result.text,
                        context=TurnContext(
                            user_id=speaker_result.user_id,
                            speaker_score=speaker_result.score,
                            speaker_status=speaker_result.status,
                        ),
                    )
                logger.info("brain_reply text=%s", reply_text)

                self.state = AgentState.SPEAKING
                logger.info("speaking text=%s", reply_text)
                interrupted_utterance = self._speak_reply(
                    TTSRequest(
                        text=reply_text,
                        voice=self.config.tts_voice,
                        rate=self.config.tts_rate,
                    )
                )
                logger.info("speaking_done")
                if interrupted_utterance is not None:
                    pending_turn = interrupted_utterance
                    conversation_active = True
                    logger.info("speaking_barge_in followup_queued")
                else:
                    self._speak_task_notifications()

                consume_standby = getattr(self.brain, "consume_return_to_standby", None)
                if callable(consume_standby) and consume_standby():
                    self._end_brain_session()
                    conversation_active = self.config.wake_word_detector is None
                    pending_turn = None
                    logger.info("conversation_control return_to_standby")

                logger.info("conversation_turn_complete turns=%d", self.turn_count)

        except KeyboardInterrupt:
            logger.info("agent_interrupted")
            self.state = AgentState.SHUTDOWN
        finally:
            self._end_brain_session()
            self.state = AgentState.SHUTDOWN
            logger.info("agent_stopped")

    def _begin_brain_session(self) -> None:
        begin_session = getattr(self.brain, "begin_session", None)
        if callable(begin_session):
            begin_session()

    def _end_brain_session(self) -> None:
        end_session = getattr(self.brain, "end_session", None)
        if callable(end_session):
            end_session()

    def _speak_task_notifications(self) -> None:
        consume = getattr(self.brain, "consume_task_notifications", None)
        if not callable(consume):
            return
        for text in consume():
            logger.info("task_notification text=%s", text)
            self.speaker.synthesize(
                TTSRequest(
                    text=text,
                    voice=self.config.tts_voice,
                    rate=self.config.tts_rate,
                )
            )

    def _warm_up_transcriber(self) -> None:
        warmup = getattr(self.transcriber, "warmup", None)
        if not callable(warmup):
            return

        logger.info("stt_warmup_started provider=%s", self.config.stt_provider)
        started_at = time.monotonic()
        warmup()
        logger.info(
            "stt_warmup_done provider=%s elapsed=%.1fs",
            self.config.stt_provider,
            time.monotonic() - started_at,
        )

        ready_text = "麥芽糖上線囉！"
        self.state = AgentState.SPEAKING
        logger.info("ready_prompt text=%s", ready_text)
        self.speaker.synthesize(
            TTSRequest(
                text=ready_text,
                voice=self.config.tts_voice,
                rate=self.config.tts_rate,
            )
        )
        logger.info("ready_prompt_done")

    def _speak_wake_ack(self) -> None:
        if not self.config.wake_ack_text:
            return

        previous_state = self.state
        self.state = AgentState.SPEAKING
        logger.info("wake_ack speaking text=%s", self.config.wake_ack_text)
        self.speaker.synthesize(
            TTSRequest(
                text=self.config.wake_ack_text,
                voice=self.config.tts_voice,
                rate=self.config.tts_rate,
            )
        )
        logger.info("wake_ack_done")
        self.state = previous_state

    def _speak_reply(self, request: TTSRequest) -> PendingTurn | None:
        """Speak once and let the brain classify a completed barge-in utterance."""
        stop_speaking = getattr(self.speaker, "stop", None)
        if not self.config.interruptible_tts or not callable(stop_speaking):
            self.speaker.synthesize(request)
            return None

        speaking_done = threading.Event()
        speaking_error: list[BaseException] = []

        def speak() -> None:
            try:
                self.speaker.synthesize(request)
            except BaseException as exc:
                speaking_error.append(exc)
            finally:
                speaking_done.set()

        speaking_thread = threading.Thread(target=speak, name="myagent-speech")
        speaking_thread.start()
        pending_utterance: Utterance | None = None
        pending_transcript = ""
        speech_in_progress = False
        listener = iter(
            self._listener_factory(
                self.config.vad_settings,
                self.config.device,
                None,
                None,
                0.0,
                0,
            )
        )
        try:
            while not speaking_done.is_set() or speech_in_progress:
                try:
                    event = next(listener)
                except StopIteration:
                    break
                if event.kind == "speech_started":
                    speech_in_progress = True
                    logger.info("speech_barge_in_started awaiting_interrupt_decision")
                elif event.kind == "speech_ended" and event.utterance is not None:
                    speech_in_progress = False
                    pending_utterance = event.utterance
                    transcript, speaker_result = self._transcribe_barge_in(
                        event.utterance
                    )
                    pending_transcript = transcript
                    should_interrupt = self._should_interrupt_speech(transcript)
                    logger.info(
                        "speech_barge_in_decision interrupt=%s transcript=%s",
                        should_interrupt,
                        transcript,
                    )
                    if should_interrupt:
                        stop_speaking()
                        break
                    # Keep monitoring while the current speech is still active. A
                    # first false classification must not create a blind interval
                    # before the user can try an explicit stop command again.
        finally:
            close_listener = getattr(listener, "close", None)
            if callable(close_listener):
                close_listener()
            speaking_thread.join()

        if speaking_error:
            raise speaking_error[0]
        if pending_utterance is None:
            return None
        if not pending_transcript:
            return None
        return PendingTurn(pending_utterance, pending_transcript, speaker_result)

    def _transcribe_barge_in(self, utterance: Utterance) -> tuple[str, SpeakerResult]:
        try:
            with tempfile.NamedTemporaryFile(suffix=".wav") as audio:
                write_utterance_wav(Path(audio.name), self._prepare_stt_utterance(utterance))
                stt_request = STTRequest(
                    audio_path=Path(audio.name),
                    model_size=self.config.whisper_model,
                    language=self.config.whisper_language,
                    compute_type=self.config.whisper_compute_type,
                )
                with ThreadPoolExecutor(max_workers=2) as executor:
                    stt_future = executor.submit(self.transcriber.transcribe, stt_request)
                    speaker_future = executor.submit(
                        self._speaker_identifier.identify, Path(audio.name)
                    )
                    result = stt_future.result()
                    speaker_result = speaker_future.result()
                return result.text.strip(), speaker_result
        except Exception as exc:
            logger.warning("speech_barge_in_stt_failed error=%s", exc)
            return "", SpeakerResult(None, None, "unknown")

    def _should_interrupt_speech(self, transcript: str) -> bool:
        normalized = re.sub(r"[\s\W_]+", "", transcript, flags=re.UNICODE).lower()
        explicit_stop_phrases = (
            "等等",
            "等一下",
            "停一下",
            "先別說了",
            "先不要說了",
            "不要繼續",
            "停止播放",
            "取消播放",
            "退下吧",
        )
        if any(phrase in normalized for phrase in explicit_stop_phrases):
            logger.info("speech_interrupt_fast_path transcript=%s", transcript)
            return True
        classifier = getattr(self.brain, "should_interrupt_speech", None)
        if not callable(classifier):
            return False
        try:
            return bool(classifier(transcript))
        except Exception as exc:
            logger.warning("speech_interrupt_decision_failed error=%s", exc)
            return False

    def _prepare_stt_utterance(self, utterance: Utterance) -> Utterance:
        if not self.config.normalize_stt_audio:
            stats = measure_utterance(utterance)
            logger.info(
                "stt_audio_stats duration=%.2fs rms=%d peak=%d gain=1.00 normalized=false",
                stats.duration_seconds,
                stats.rms,
                stats.peak,
            )
            return utterance

        result = normalize_utterance_peak(
            utterance,
            target_peak=self.config.stt_target_peak,
            min_peak=self.config.stt_min_peak,
            max_gain=self.config.stt_max_gain,
        )
        logger.info(
            "stt_audio_stats duration=%.2fs rms=%d->%d peak=%d->%d gain=%.2f normalized=%s",
            result.before.duration_seconds,
            result.before.rms,
            result.after.rms,
            result.before.peak,
            result.after.peak,
            result.gain,
            result.gain != 1.0,
        )
        return result.utterance


def _next_output_path(output_dir: Path, turn_count: int) -> Path:
    stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    return output_dir / f"agent-turn-{turn_count:03d}-{stamp}.wav"


def _is_wake_only(text: str, wake_keywords: tuple[str, ...]) -> bool:
    normalized = re.sub(r"[\s\W_]+", "", text, flags=re.UNICODE)
    return bool(normalized) and normalized in {
        re.sub(r"[\s\W_]+", "", keyword, flags=re.UNICODE)
        for keyword in wake_keywords
    }
