from __future__ import annotations

import logging
import queue
import re
import inspect
import tempfile
import threading
import time
import uuid
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime
from dataclasses import dataclass, replace
from enum import Enum
from pathlib import Path
from typing import Callable, Iterator, Protocol

from maltose.agent.brain import AgentBrain, EchoBrain, TurnContext
from maltose.agent.config import AgentConfig
from maltose.runtime import EventHub
from maltose.runtime.control import AutonomyControl, AutonomyPaused
from contextlib import nullcontext
from maltose.voice import (
    FasterWhisperSTT,
    ListeningEvent,
    MacOSSayTTS,
    STTRequest,
    STTResult,
    TTSRequest,
    Utterance,
    VADSettings,
    WakeWordDetector,
    AudioInputDeviceController,
    measure_utterance,
    normalize_utterance_peak,
    NullSpeakerIdentifier,
    RenderedAudio,
    SpeakerIdentifier,
    SpeakerIdentityManager,
    SpeakerResult,
    create_stt_provider,
    write_utterance_wav,
)
from maltose.voice.listening import microphone_events

logger = logging.getLogger(__name__)

_CJK_CHARACTER = re.compile(r"[\u3400-\u4dbf\u4e00-\u9fff\uf900-\ufaff]")


def _is_single_character_transcript(text: str) -> bool:
    """Return whether STT produced only one Chinese character (ignoring punctuation)."""
    normalized = re.sub(r"[\W_]+", "", text.strip(), flags=re.UNICODE)
    return len(normalized) == 1 and _CJK_CHARACTER.fullmatch(normalized) is not None


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
    interrupt_requested: bool = True
    captured_epoch: int | None = None


ListenerFactory = Callable[
    [VADSettings, str | int | None, float | None, WakeWordDetector | None, float, int],
    Iterator[ListeningEvent],
]


class ObservableSpeaker:
    def __init__(self,provider,publish):self._provider=provider;self._publish=publish
    def __getattr__(self,name):
        value=getattr(self._provider,name)
        if name not in ("synthesize","play") or not callable(value):return value
        def observed(*args,**kwargs):
            self._publish("speech_started",{})
            try:return value(*args,**kwargs)
            finally:self._publish("speech_finished",{})
        return observed


class ControlledSpeaker:
    def __init__(self, provider, control): self._provider, self._control = provider, control
    def __getattr__(self, name):
        value = getattr(self._provider, name)
        if name not in ('synthesize', 'render', 'play') or not callable(value): return value
        def admitted(*args, **kwargs):
            with self._control.activity('speech'):
                return value(*args, **kwargs)
        return admitted


@dataclass(frozen=True)
class QueuedAgentInput:
    text: str
    source: str
    captured_epoch: int | None
    message_id: str
    # Runtime-owned callback, never a serialized identity supplied by the UI.
    voice_context: Callable[[], TurnContext | None] | None = None


class VoiceAgent:
    """Main Voice Agent controlling standby, listening, thinking, and speaking."""

    def __init__(
        self,
        config: AgentConfig | None = None,
        brain: AgentBrain | None = None,
        transcriber: STTProvider | None = None,
        speaker: TTSProvider | None = None,
        speaker_identifier: SpeakerIdentifier | None = None,
        speaker_identity_manager: SpeakerIdentityManager | None = None,
        listener_factory: ListenerFactory = microphone_events,
        event_hub: EventHub | None = None,
        audio_device_controller: AudioInputDeviceController | None = None,
        observe_speech: bool = False,
        voice_enabled: bool = True,
        control_gate: AutonomyControl | None = None,
        input_router: Callable | None = None,
    ) -> None:
        self.config = config or AgentConfig()
        self.brain = brain or EchoBrain()
        self._transcriber = transcriber
        self._speaker = speaker
        self._observable_speaker = None
        self._controlled_speaker = None
        self.control_gate = control_gate
        self.input_router = input_router
        self.voice_context_observer = None
        self._assistant_stream_id = None
        self._assistant_stream_text = ''
        self._observe_speech = observe_speech
        self._voice_enabled = voice_enabled
        self._shutdown_requested = threading.Event()
        self._audio_input_count = 0
        self._audio_input_lock = threading.Lock()
        self._speaker_identifier = speaker_identifier or NullSpeakerIdentifier()
        self._speaker_identity_manager = speaker_identity_manager
        self._listener_factory = listener_factory
        self._event_hub = event_hub
        self._audio_device_controller = audio_device_controller
        self._command_queue: queue.Queue[QueuedAgentInput] = queue.Queue()
        self._state = AgentState.INITIALIZING
        self.turn_count = 0

    @property
    def state(self) -> AgentState:
        return self._state

    @state.setter
    def state(self, value: AgentState) -> None:
        self._state = value
        if self._event_hub is not None:
            self._event_hub.publish("state_changed", {"state": value.value})

    def submit_text(self, text: str, *, source: str = "web", message_id: str | None = None) -> None:
        """Queue text from a non-voice interface for the current Agent session."""
        if not text.strip():
            raise ValueError("Agent text input cannot be empty")
        if source not in {"web", "native"}: raise ValueError("Unknown Agent text input source")
        if message_id is not None and (not isinstance(message_id, str) or not message_id or len(message_id) > 128): raise ValueError('Invalid input ID')
        self._command_queue.put(QueuedAgentInput(text, source, self.control_gate.epoch if self.control_gate else None, message_id or uuid.uuid4().hex))

    def submit_routed_voice(self, text: str, *, message_id: str, context_provider: Callable[[], TurnContext | None]) -> None:
        """Re-admit a runtime-verified voice input after the controller hands back."""
        if not text.strip() or not message_id or not callable(context_provider): raise ValueError('Invalid routed voice input')
        self._command_queue.put(QueuedAgentInput(text, 'voice', self.control_gate.epoch if self.control_gate else None,
                                                 message_id, context_provider))

    def request_shutdown(self) -> None:
        """Cooperatively wake the listener and stop this runtime, not another process."""
        self._shutdown_requested.set()
        self.state = AgentState.SHUTDOWN

    @property
    def audio_input_active(self) -> bool:
        with self._audio_input_lock: return self._audio_input_count > 0

    def _audio_input_changed(self, active: bool) -> None:
        with self._audio_input_lock:
            self._audio_input_count = max(0, self._audio_input_count + (1 if active else -1))
            count = self._audio_input_count
        self._publish("audio_input_state", {"active": count > 0, "streams": count})
        logger.info("audio_input_state active=%s streams=%d", count > 0, count)

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
        provider = self._speaker
        if self._observe_speech:
            if self._observable_speaker is None:
                self._observable_speaker=ObservableSpeaker(self._speaker,self._publish)
            provider = self._observable_speaker
        if self.control_gate:
            if self._controlled_speaker is None: self._controlled_speaker = ControlledSpeaker(provider, self.control_gate)
            return self._controlled_speaker
        return provider

    def run(self) -> None:
        logger.info(
            "agent_starting conversation_timeout=%.1fs",
            self.config.standby_timeout,
        )

        try:
            self._warm_up_transcriber()
            conversation_active = self.config.wake_word_detector is None
            brain_session_open = False
            if conversation_active and (not self.control_gate or self.control_gate.active):
                self._begin_brain_session()
                brain_session_open = True
            pending_turn: PendingTurn | None = None
            while self.state != AgentState.SHUTDOWN and not self._shutdown_requested.is_set():
                self.state = AgentState.STANDBY
                logger.info(
                    "agent_standby wake_required=%s conversation_timeout=%s",
                    not conversation_active,
                    self.config.standby_timeout if conversation_active else "disabled",
                )
                self._speak_task_notifications()

                captured_utterance = pending_turn.utterance if pending_turn else None
                captured_epoch = pending_turn.captured_epoch if pending_turn and pending_turn.captured_epoch is not None else self.control_gate.epoch if self.control_gate else None
                pretranscribed_turn = pending_turn
                pending_turn = None
                external_text: str | None = None
                external_source = "web"
                external_message_id = None
                external_voice_context = None
                queued_input = None
                if captured_utterance is None:
                    listening_events: queue.Queue[object] = queue.Queue()
                    listener_stop = threading.Event()

                    def receive_listening_events() -> None:
                        try:
                            for event in self._invoke_listener(listener_stop, conversation_active):
                                listening_events.put(event)
                        except BaseException as exc:
                            listening_events.put(exc)
                        finally:
                            listening_events.put(None)

                    listener_thread = threading.Thread(
                        target=receive_listening_events,
                        name="myagent-listener",
                        daemon=True,
                    )
                    listener_thread.start()
                    while captured_utterance is None and external_text is None and not self._shutdown_requested.is_set():
                        try:
                            queued_input = self._command_queue.get_nowait()
                            external_text, external_source = queued_input.text, queued_input.source
                            captured_epoch, external_message_id = queued_input.captured_epoch, queued_input.message_id
                            listener_stop.set()
                            break
                        except queue.Empty:
                            pass
                        try:
                            event = listening_events.get(timeout=0.05)
                        except queue.Empty:
                            continue
                        if event is None:
                            break
                        if isinstance(event, BaseException):
                            raise event
                        if event.kind == "standby_timeout":
                            logger.info(
                                "conversation_silence_timeout returning_to_listening_without_ending_session"
                            )
                            conversation_active = self.config.wake_word_detector is None
                            break
                        elif event.kind == "speech_started":
                            self.state = AgentState.LISTENING
                            logger.info("speech_started")
                        elif event.kind == "wake_detected":
                            logger.info("wake_detected keyword=%s", event.keyword)
                            if not brain_session_open:
                                try:
                                    with self.control_gate.activity('conversation_control') if self.control_gate else nullcontext():
                                        self._begin_brain_session()
                                        brain_session_open = True
                                        logger.info("conversation_session_resumed")
                                except AutonomyPaused: pass
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
                    listener_stop.set()
                    listener_thread.join(timeout=1.0)

                if external_text is not None:
                    if queued_input.voice_context is not None:
                        external_voice_context = queued_input.voice_context()
                        if external_voice_context is None or (self.control_gate and
                                (not self.control_gate.active or captured_epoch != self.control_gate.epoch)):
                            self._publish('input_deferred', {'message_id': external_message_id, 'source': 'voice',
                                'reason': 'Voice verification or control changed before admission'})
                            continue
                    result = STTResult(
                        text=external_text,
                        language=self.config.whisper_language,
                        duration=0.0,
                        segments=[],
                    )
                    speaker_result = (SpeakerResult(external_voice_context.user_id, external_voice_context.speaker_score,
                        external_voice_context.speaker_status) if external_voice_context else SpeakerResult(None, None, "unknown"))
                elif captured_utterance is None:
                    continue

                if self.state == AgentState.SHUTDOWN:
                    break
                if captured_utterance is None:
                    self.turn_count += 1
                else:
                    self.turn_count += 1
                    path = _next_output_path(self.config.output_dir, self.turn_count)
                    stt_utterance = self._prepare_stt_utterance(captured_utterance)
                    write_utterance_wav(path, stt_utterance)

                self.state = AgentState.THINKING

                if external_text is not None:
                    pass
                elif pretranscribed_turn is not None:
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
                        if self._speaker_identity_manager is not None:
                            self._speaker_identity_manager.submit(path)
                        else:
                            speaker_future = executor.submit(self._speaker_identifier.identify, path)
                        result = stt_future.result()
                        speaker_result = (
                            self._speaker_identity_manager.snapshot()
                            if self._speaker_identity_manager is not None
                            else speaker_future.result()
                        )
                logger.info("transcript text=%s", result.text)
                if external_text is None and _is_single_character_transcript(result.text):
                    logger.info(
                        "single_character_transcript_ignored text=%r",
                        result.text.strip(),
                    )
                    continue
                logger.info(
                    "speaker_result user_id=%s score=%s status=%s",
                    speaker_result.user_id,
                    speaker_result.score,
                    speaker_result.status,
                )
                speaker_label = self._resolve_speaker_label(speaker_result)
                logger.info(
                    "user_utterance user=%s text=%s",
                    speaker_label,
                    result.text.strip(),
                )
                if not result.text.strip():
                    logger.info("empty_transcript_ignored")
                    continue

                source = external_source if external_text is not None else 'voice'
                turn_context = TurnContext(user_id=speaker_result.user_id, speaker_score=speaker_result.score,
                                           speaker_status=speaker_result.status, input_source=source)
                if external_text is None and self.voice_context_observer:
                    self.voice_context_observer(turn_context)
                if external_text is None and self.control_gate and not self.control_gate.active and _is_wake_only(result.text, self.config.wake_keywords):
                    conversation_active = True
                    self._publish('voice_wake_observed', {'recipient': 'current'})
                    continue
                input_id = external_message_id or uuid.uuid4().hex
                input_text = result.text if external_text is not None else result.text.strip()
                if external_voice_context is None and self.input_router and self.input_router(input_text, turn_context, source, captured_epoch, input_id):
                    continue
                admitted = False
                try:
                    with self.control_gate.activity('conversation', expected_epoch=captured_epoch) if self.control_gate else nullcontext():
                        admitted = True
                        if not brain_session_open:
                            self._begin_brain_session(); brain_session_open = True
                        self._publish("user_message", {"message_id": input_id, "content": input_text, "source": source})
                        reply_text, interrupted_utterance, streamed_reply = self._respond_to_input(result.text, turn_context)
                        if interrupted_utterance and interrupted_utterance.captured_epoch is None:
                            interrupted_utterance = replace(interrupted_utterance, captured_epoch=captured_epoch)
                        logger.info("brain_reply text=%s", reply_text)
                        if not streamed_reply:
                            self._publish("assistant_message", {"content": reply_text})
                except AutonomyPaused:
                    if not admitted:
                        if external_voice_context is not None:
                            self._publish('input_deferred', {'message_id': input_id, 'source': 'voice',
                                'reason': 'Control changed before routed voice admission'})
                        elif self.input_router:
                            self.input_router(input_text, turn_context, source, captured_epoch, input_id)
                    if self._assistant_stream_id:
                        self._finish_assistant_stream(self._assistant_stream_id, self._assistant_stream_text, interrupted=True)
                    self._publish('autonomy_turn_interrupted', {'reason': 'control_handoff', 'messageID': input_id})
                    logger.info('autonomy_turn_interrupted')
                    continue
                logger.info("speaking_done")
                if interrupted_utterance is not None:
                    conversation_active = True
                    if interrupted_utterance.interrupt_requested:
                        pending_turn = None
                        self.state = AgentState.LISTENING
                        logger.info("speaking_barge_in interrupted_return_to_listening")
                    else:
                        pending_turn = interrupted_utterance
                        logger.info("speaking_barge_in followup_queued")
                else:
                    self._speak_task_notifications()

                consume_standby = getattr(self.brain, "consume_return_to_standby", None)
                if callable(consume_standby) and consume_standby():
                    try:
                        with self.control_gate.activity('conversation_control') if self.control_gate else nullcontext():
                            self._end_brain_session()
                            brain_session_open = False
                            conversation_active = self.config.wake_word_detector is None
                            pending_turn = None
                            logger.info("conversation_control return_to_standby")
                    except AutonomyPaused: pass

                logger.info("conversation_turn_complete turns=%d", self.turn_count)

        except KeyboardInterrupt:
            logger.info("agent_interrupted")
            self.state = AgentState.SHUTDOWN
        finally:
            if self._speaker_identity_manager is not None:
                self._speaker_identity_manager.close()
            self._end_brain_session()
            self.state = AgentState.SHUTDOWN
            logger.info("agent_stopped")

    def _respond_to_input(self, text, turn_context):
        if _is_wake_only(text, self.config.wake_keywords):
            reply_text = self.config.wake_ack_text or "我在"
            logger.info("wake_only_reply text=%s", reply_text)
            interrupted_utterance = self._speak_reply(TTSRequest(
                text=reply_text, voice=self.config.tts_voice, rate=self.config.tts_rate))
            streamed_reply = False
        else:
            stream_process = getattr(self.brain, "process_stream", None)
            if callable(stream_process):
                reply_text, interrupted_utterance = self._speak_stream(stream_process(text, context=turn_context))
                streamed_reply = True
            else:
                reply_text = self.brain.process(text, context=turn_context)
                interrupted_utterance = self._speak_reply(TTSRequest(
                    text=reply_text, voice=self.config.tts_voice, rate=self.config.tts_rate))
                streamed_reply = False
        return reply_text, interrupted_utterance, streamed_reply

    def _begin_brain_session(self) -> None:
        begin_session = getattr(self.brain, "begin_session", None)
        if callable(begin_session):
            begin_session()

    def _end_brain_session(self) -> None:
        end_session = getattr(self.brain, "end_session", None)
        if callable(end_session):
            end_session()

    def _publish(self, event_type: str, payload: dict[str, object]) -> None:
        if self._event_hub is not None:
            self._event_hub.publish(event_type, payload)

    def publish_ui_block(self, block_type: str, payload: dict[str, object]) -> None:
        """Publish a UI block for Web and other runtime presentations."""
        block_type = block_type.strip()
        if not block_type:
            raise ValueError("block_type cannot be empty")
        self._publish("ui_block", {"block_type": block_type, **payload})

    def _start_assistant_stream(self) -> str:
        message_id = uuid.uuid4().hex
        self._assistant_stream_id = message_id; self._assistant_stream_text = ''
        self._publish("assistant_start", {"message_id": message_id})
        return message_id

    def _publish_assistant_delta(self, message_id: str, content: str) -> None:
        if self._assistant_stream_id == message_id: self._assistant_stream_text += content
        self._publish(
            "assistant_delta",
            {"message_id": message_id, "content": content},
        )

    def _finish_assistant_stream(
        self,
        message_id: str,
        content: str,
        *,
        interrupted: bool = False,
    ) -> None:
        if self._assistant_stream_id == message_id:
            self._assistant_stream_id = None; self._assistant_stream_text = ''
        self._publish(
            "assistant_end",
            {
                "message_id": message_id,
                "content": content,
                "interrupted": interrupted,
            },
        )

    def _invoke_listener(
        self,
        stop_event: threading.Event,
        conversation_active: bool,
    ) -> Iterator[ListeningEvent]:
        if not self._voice_enabled:
            def wait_for_input():
                while not stop_event.wait(0.05):
                    if self._shutdown_requested.is_set():
                        return
                yield from ()
            return wait_for_input()
        device = (
            self._audio_device_controller.device_for_stream()
            if self._audio_device_controller is not None
            else self.config.device
        )
        arguments = (
            self.config.vad_settings,
            device,
            self.config.standby_timeout if conversation_active else None,
            None if conversation_active else self.config.wake_word_detector,
            self.config.wake_ack_delay,
            self.config.wake_buffer_ms,
        )
        return self._listener_with_lifecycle(arguments, stop_event)

    def _listener_with_lifecycle(self, arguments: tuple, stop_event: threading.Event | None = None) -> Iterator[ListeningEvent]:
        try:
            signature = inspect.signature(self._listener_factory)
            audio_state = {"on_audio_state": self._audio_input_changed} if "on_audio_state" in signature.parameters else {}
            stop_parameter = signature.parameters.get("stop_event")
            stop_as_keyword = stop_parameter is not None and stop_parameter.kind != inspect.Parameter.POSITIONAL_ONLY
            accepts_stop_event = (
                any(
                    parameter.kind == inspect.Parameter.VAR_POSITIONAL
                    for parameter in signature.parameters.values()
                )
                or sum(parameter.kind in (inspect.Parameter.POSITIONAL_ONLY, inspect.Parameter.POSITIONAL_OR_KEYWORD)
                       for parameter in signature.parameters.values()) >= 7
            )
        except (TypeError, ValueError):
            accepts_stop_event = False
            stop_as_keyword = False
            audio_state = {}
        if stop_as_keyword:
            return self._listener_factory(*arguments, stop_event=stop_event, **audio_state)
        if accepts_stop_event:
            return self._listener_factory(*arguments, stop_event, **audio_state)
        return self._listener_factory(*arguments, **audio_state)

    def _speak_task_notifications(self) -> None:
        try:
            with self.control_gate.activity('notifications') if self.control_gate else nullcontext():
                self._speak_admitted_notifications()
        except AutonomyPaused: return

    def _speak_admitted_notifications(self) -> None:
        consume = getattr(self.brain, "consume_task_notifications", None)
        if not callable(consume):
            return
        for text in consume():
            logger.info("task_notification text=%s", text)
            if not self._voice_enabled:
                self._publish("assistant_message", {"content": text})
                continue
            self.speaker.synthesize(
                TTSRequest(
                    text=text,
                    voice=self.config.tts_voice,
                    rate=self.config.tts_rate,
                )
            )

    def _speak_stream(self, chunks: Iterator[str]) -> tuple[str, PendingTurn | None]:
        """Coordinate LLM streaming, sentence TTS, and optional barge-in listening."""
        if not self._voice_enabled:
            message_id = self._start_assistant_stream()
            parts = []
            for chunk in chunks:
                if self._shutdown_requested.is_set():
                    break
                parts.append(chunk)
                self._publish_assistant_delta(message_id, chunk)
            text = "".join(parts)
            self._finish_assistant_stream(message_id, text, interrupted=self._shutdown_requested.is_set())
            return text, None
        if callable(getattr(self.speaker, "render", None)) and callable(
            getattr(self.speaker, "play", None)
        ):
            return self._speak_stream_with_rendered_audio(chunks)
        self.state = AgentState.SPEAKING
        message_id = self._start_assistant_stream()
        buffer = ""
        spoken_parts: list[str] = []
        assistant_parts: list[str] = []
        punctuation = re.compile(r"[。！？!?；;\n]")
        deferred: PendingTurn | None = None
        stream_queue: queue.Queue[object] = queue.Queue()
        stream_done = object()
        stream_stop = threading.Event()

        def receive_stream() -> None:
            try:
                for chunk in chunks:
                    if stream_stop.is_set():
                        break
                    stream_queue.put(chunk)
            except BaseException as exc:
                stream_queue.put(exc)
            finally:
                close_stream = getattr(chunks, "close", None)
                if callable(close_stream):
                    close_stream()
                stream_queue.put(stream_done)

        receiver = threading.Thread(target=receive_stream, name="myagent-llm-stream")
        receiver.start()
        pending_sentences: queue.Queue[str] = queue.Queue()
        tts_thread: threading.Thread | None = None
        tts_error: list[BaseException] = []
        listener_events: queue.Queue[object] = queue.Queue()
        listener_stop = threading.Event()
        listener_thread: threading.Thread | None = None

        can_listen = self.config.interruptible_tts and callable(getattr(self.speaker, "stop", None))
        if can_listen:
            listener = self._create_stream_listener(listener_stop)

            def receive_listener_events() -> None:
                try:
                    for event in listener:
                        listener_events.put(event)
                finally:
                    listener_events.put(None)

            listener_thread = threading.Thread(
                target=receive_listener_events,
                name="myagent-stream-listener",
                daemon=True,
            )
            listener_thread.start()

        def speak_next() -> None:
            sentence = pending_sentences.get()
            try:
                self.speaker.synthesize(
                    TTSRequest(text=sentence, voice=self.config.tts_voice, rate=self.config.tts_rate)
                )
            except BaseException as exc:
                tts_error.append(exc)

        stream_finished = False
        interrupted = False
        try:
            while not stream_finished or not pending_sentences.empty() or tts_thread is not None:
                if tts_thread is not None and not tts_thread.is_alive():
                    tts_thread.join()
                    tts_thread = None
                    if tts_error:
                        raise tts_error[0]

                if tts_thread is None and not pending_sentences.empty():
                    tts_thread = threading.Thread(target=speak_next, name="myagent-stream-tts")
                    tts_thread.start()

                if can_listen:
                    try:
                        event = listener_events.get_nowait()
                    except queue.Empty:
                        event = None
                    if event is not None and getattr(event, "kind", None) == "speech_started":
                        logger.info("speech_barge_in_started awaiting_interrupt_decision")
                    elif event is not None and getattr(event, "kind", None) == "speech_ended":
                        utterance = getattr(event, "utterance", None)
                        if utterance is not None:
                            transcript, speaker_result = self._transcribe_barge_in(utterance)
                            should_interrupt = self._should_interrupt_speech(transcript)
                            logger.info(
                                "speech_barge_in_decision interrupt=%s transcript=%s",
                                should_interrupt,
                                transcript,
                            )
                            if transcript and should_interrupt:
                                interrupted = True
                                self.speaker.stop()
                                deferred = PendingTurn(
                                    utterance, transcript, speaker_result, interrupt_requested=True
                                )
                                break
                            if transcript:
                                deferred = PendingTurn(
                                    utterance, transcript, speaker_result, interrupt_requested=False
                                )

                try:
                    item = stream_queue.get(timeout=0.03)
                except queue.Empty:
                    continue
                if item is stream_done:
                    stream_finished = True
                    if buffer.strip():
                        pending_sentences.put(self._clean_spoken_sentence(buffer))
                        buffer = ""
                    continue
                if isinstance(item, BaseException):
                    raise item
                if not isinstance(item, str) or not item:
                    continue
                assistant_parts.append(item)
                self._publish_assistant_delta(message_id, item)
                buffer += item
                while True:
                    match = punctuation.search(buffer)
                    if match is None:
                        break
                    sentence = self._clean_spoken_sentence(buffer[: match.end()])
                    buffer = buffer[match.end():]
                    if sentence:
                        spoken_parts.append(sentence)
                        logger.info("stream_sentence text=%s", sentence)
                        pending_sentences.put(sentence)
        finally:
            stream_stop.set()
            listener_stop.set()
            if tts_thread is not None:
                tts_thread.join()
            receiver.join(timeout=1.0)
            if listener_thread is not None:
                listener_thread.join(timeout=1.0)

        self._finish_assistant_stream(
            message_id,
            "".join(assistant_parts),
            interrupted=interrupted,
        )
        if interrupted:
            return "".join(spoken_parts), deferred
        return "".join(spoken_parts), deferred

    def _speak_stream_with_rendered_audio(
        self, chunks: Iterator[str]
    ) -> tuple[str, PendingTurn | None]:
        """Stream sentences while rendering the next audio artifact ahead of playback."""
        self.state = AgentState.SPEAKING
        message_id = self._start_assistant_stream()
        buffer = ""
        spoken_parts: list[str] = []
        assistant_parts: list[str] = []
        punctuation = re.compile(r"[。！？!?；;\n]")
        deferred: PendingTurn | None = None
        stream_queue: queue.Queue[object] = queue.Queue()
        stream_done = object()
        sentence_done = object()
        audio_done = object()
        stream_stop = threading.Event()
        listener_stop = threading.Event()
        pipeline_stop = threading.Event()
        sentence_queue: queue.Queue[object] = queue.Queue()
        audio_queue: queue.Queue[object] = queue.Queue(maxsize=2)
        tts_error: list[BaseException] = []

        def receive_stream() -> None:
            try:
                for chunk in chunks:
                    if stream_stop.is_set():
                        break
                    stream_queue.put(chunk)
            except BaseException as exc:
                stream_queue.put(exc)
            finally:
                close_stream = getattr(chunks, "close", None)
                if callable(close_stream):
                    close_stream()
                stream_queue.put(stream_done)

        receiver = threading.Thread(target=receive_stream, name="myagent-llm-stream")
        receiver.start()

        def render_audio() -> None:
            try:
                while not pipeline_stop.is_set():
                    item = sentence_queue.get()
                    if item is sentence_done:
                        break
                    artifact = self.speaker.render(
                        TTSRequest(
                            text=item,
                            voice=self.config.tts_voice,
                            rate=self.config.tts_rate,
                        )
                    )
                    while not pipeline_stop.is_set():
                        try:
                            audio_queue.put(artifact, timeout=0.05)
                            break
                        except queue.Full:
                            continue
                    else:
                        artifact.cleanup()
                        break
            except BaseException as exc:
                tts_error.append(exc)
            finally:
                audio_queue.put(audio_done)

        renderer = threading.Thread(target=render_audio, name="myagent-tts-render")
        renderer.start()

        can_listen = self.config.interruptible_tts and callable(getattr(self.speaker, "stop", None))
        listener_events: queue.Queue[object] = queue.Queue()
        listener_thread: threading.Thread | None = None
        if can_listen:
            listener = self._create_stream_listener(listener_stop)

            def receive_listener_events() -> None:
                try:
                    for event in listener:
                        listener_events.put(event)
                finally:
                    listener_events.put(None)

            listener_thread = threading.Thread(
                target=receive_listener_events,
                name="myagent-stream-listener",
                daemon=True,
            )
            listener_thread.start()

        playback_thread: threading.Thread | None = None
        current_audio: RenderedAudio | None = None
        playback_finished = False
        interrupted = False
        try:
            while not playback_finished or playback_thread is not None:
                if playback_thread is not None and not playback_thread.is_alive():
                    playback_thread.join()
                    playback_thread = None
                    if current_audio is not None:
                        current_audio.cleanup()
                        current_audio = None
                    if tts_error:
                        raise tts_error[0]

                if playback_thread is None and not playback_finished:
                    try:
                        audio = audio_queue.get_nowait()
                    except queue.Empty:
                        audio = None
                    if audio is audio_done:
                        playback_finished = True
                    elif isinstance(audio, RenderedAudio):
                        current_audio = audio

                        def play_current(artifact: RenderedAudio = audio) -> None:
                            try:
                                self.speaker.play(artifact)
                            except BaseException as exc:
                                tts_error.append(exc)

                        playback_thread = threading.Thread(
                            target=play_current,
                            name="myagent-tts-play",
                        )
                        playback_thread.start()

                if can_listen:
                    try:
                        event = listener_events.get_nowait()
                    except queue.Empty:
                        event = None
                    if event is not None and getattr(event, "kind", None) == "speech_started":
                        logger.info("speech_barge_in_started awaiting_interrupt_decision")
                    elif event is not None and getattr(event, "kind", None) == "speech_ended":
                        utterance = getattr(event, "utterance", None)
                        if utterance is not None:
                            transcript, speaker_result = self._transcribe_barge_in(utterance)
                            should_interrupt = self._should_interrupt_speech(transcript)
                            logger.info(
                                "speech_barge_in_decision interrupt=%s transcript=%s",
                                should_interrupt,
                                transcript,
                            )
                            if transcript and should_interrupt:
                                interrupted = True
                                self.speaker.stop()
                                deferred = PendingTurn(
                                    utterance, transcript, speaker_result, interrupt_requested=True
                                )
                                break
                            if transcript:
                                deferred = PendingTurn(
                                    utterance, transcript, speaker_result, interrupt_requested=False
                                )

                try:
                    item = stream_queue.get(timeout=0.03)
                except queue.Empty:
                    continue
                if item is stream_done:
                    if buffer.strip():
                        sentence_queue.put(self._clean_spoken_sentence(buffer))
                        buffer = ""
                    sentence_queue.put(sentence_done)
                    continue
                if isinstance(item, BaseException):
                    raise item
                if not isinstance(item, str) or not item:
                    continue
                assistant_parts.append(item)
                self._publish_assistant_delta(message_id, item)
                buffer += item
                while True:
                    match = punctuation.search(buffer)
                    if match is None:
                        break
                    sentence = self._clean_spoken_sentence(buffer[: match.end()])
                    buffer = buffer[match.end():]
                    if sentence:
                        spoken_parts.append(sentence)
                        logger.info("stream_sentence text=%s", sentence)
                        sentence_queue.put(sentence)
        finally:
            stream_stop.set()
            listener_stop.set()
            pipeline_stop.set()
            sentence_queue.put(sentence_done)
            if interrupted:
                self.speaker.stop()
            renderer.join(timeout=2.0)
            if playback_thread is not None:
                self.speaker.stop()
                playback_thread.join(timeout=2.0)
            if current_audio is not None:
                current_audio.cleanup()
            while True:
                try:
                    queued_audio = audio_queue.get_nowait()
                except queue.Empty:
                    break
                if isinstance(queued_audio, RenderedAudio):
                    queued_audio.cleanup()
            receiver.join(timeout=1.0)
            if listener_thread is not None:
                listener_thread.join(timeout=1.0)

        if tts_error and not interrupted:
            raise tts_error[0]
        self._finish_assistant_stream(
            message_id,
            "".join(assistant_parts),
            interrupted=interrupted,
        )
        return "".join(spoken_parts), deferred

    def _create_stream_listener(self, stop_event: threading.Event) -> Iterator[ListeningEvent]:
        device = (
            self._audio_device_controller.device_for_stream()
            if self._audio_device_controller is not None
            else self.config.device
        )
        return iter(self._listener_with_lifecycle((self.config.vad_settings, device, None, None, 0.0, 0), stop_event))

    @staticmethod
    def _clean_spoken_sentence(text: str) -> str:
        text = text.strip()
        text = re.sub(r"^#{1,6}\s*", "", text)
        text = re.sub(r"^[-*+]\s+", "", text)
        text = text.replace("```", "")
        return text.strip()

    def _warm_up_transcriber(self) -> None:
        if not self._voice_enabled:
            return
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

        ready_text = "你好，我是麥芽糖。"
        if self.control_gate and not self.control_gate.active: return
        self.state = AgentState.SPEAKING
        logger.info("ready_prompt text=%s", ready_text)
        try: self.speaker.synthesize(TTSRequest(text=ready_text, voice=self.config.tts_voice, rate=self.config.tts_rate))
        except AutonomyPaused: return
        logger.info("ready_prompt_done")

    def _speak_wake_ack(self) -> None:
        if not self.config.wake_ack_text:
            return
        if self.control_gate and not self.control_gate.active: return

        previous_state = self.state
        self.state = AgentState.SPEAKING
        logger.info("wake_ack speaking text=%s", self.config.wake_ack_text)
        try: self.speaker.synthesize(TTSRequest(text=self.config.wake_ack_text, voice=self.config.tts_voice, rate=self.config.tts_rate))
        except AutonomyPaused: pass
        logger.info("wake_ack_done")
        self.state = previous_state

    def _speak_reply(self, request: TTSRequest) -> PendingTurn | None:
        if not self._voice_enabled:
            return None
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
        interrupt_requested = False
        speech_in_progress = False
        listener = iter(
            self._listener_with_lifecycle((
                self.config.vad_settings,
                self._audio_device_controller.device_for_stream()
                if self._audio_device_controller is not None
                else self.config.device,
                None,
                None,
                0.0,
                0,
            ))
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
                    interrupt_requested = should_interrupt
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
        return PendingTurn(
            pending_utterance,
            pending_transcript,
            speaker_result,
            interrupt_requested=interrupt_requested,
        )

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
                transcript = result.text.strip()
                if _is_single_character_transcript(transcript):
                    logger.info(
                        "single_character_barge_in_ignored text=%r", transcript
                    )
                    return "", speaker_result
                return transcript, speaker_result
        except Exception as exc:
            logger.warning("speech_barge_in_stt_failed error=%s", exc)
            return "", SpeakerResult(None, None, "unknown")

    def _resolve_speaker_label(self, speaker_result: SpeakerResult) -> str:
        if not speaker_result.user_id:
            return "Unknown"
        resolver = getattr(self.brain, "resolve_user_name", None)
        if callable(resolver):
            try:
                display_name = resolver(speaker_result.user_id)
                if display_name:
                    return display_name
            except Exception:
                logger.exception(
                    "speaker_display_name_resolution_failed user_id=%s",
                    speaker_result.user_id,
                )
        return speaker_result.user_id

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
