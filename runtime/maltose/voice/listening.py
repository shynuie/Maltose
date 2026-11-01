from __future__ import annotations

import queue
import logging
from contextlib import ExitStack
import threading
import wave
from collections import deque
from dataclasses import dataclass
from pathlib import Path
from typing import Iterator, Protocol

from maltose.voice.wake import WakeWordDetector, WakeWordGate

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class VADSettings:
    sample_rate: int = 16000
    frame_ms: int = 20
    sample_width: int = 2
    channels: int = 1
    aggressiveness: int = 2
    start_trigger_ms: int = 160
    end_silence_ms: int = 700
    pre_roll_ms: int = 300
    kws_frame_ms: int | None = None
    min_speech_ms: int = 0

    def __post_init__(self) -> None:
        if self.sample_rate not in {8000, 16000, 32000, 48000}:
            raise ValueError("sample_rate must be one of 8000, 16000, 32000, or 48000.")
        if self.frame_ms not in {10, 20, 30}:
            raise ValueError("frame_ms must be 10, 20, or 30 for WebRTC VAD.")
        if self.sample_width != 2:
            raise ValueError("sample_width must be 2 bytes for 16-bit PCM audio.")
        if self.channels != 1:
            raise ValueError("channels must be 1 for mono audio.")
        if self.kws_frame_ms is not None and self.kws_frame_ms not in {10, 20, 30}:
            raise ValueError("kws_frame_ms must be 10, 20, or 30.")
        if self.min_speech_ms < 0:
            raise ValueError("min_speech_ms must be non-negative.")

    @property
    def frame_samples(self) -> int:
        return self.sample_rate * self.frame_ms // 1000

    @property
    def frame_byte_count(self) -> int:
        return self.frame_samples * self.sample_width * self.channels

    @property
    def bytes_per_second(self) -> int:
        return self.sample_rate * self.sample_width * self.channels

    @property
    def start_trigger_frames(self) -> int:
        return max(1, _ceil_div(self.start_trigger_ms, self.frame_ms))

    @property
    def end_silence_frames(self) -> int:
        return max(1, _ceil_div(self.end_silence_ms, self.frame_ms))

    @property
    def pre_roll_frames(self) -> int:
        return max(0, _ceil_div(self.pre_roll_ms, self.frame_ms))

    def frames_for_ms(self, duration_ms: int) -> int:
        return max(0, _ceil_div(duration_ms, self.frame_ms))

    @property
    def kws_frame_byte_count(self) -> int:
        frame_ms = self.kws_frame_ms or self.frame_ms
        return self.sample_rate * frame_ms // 1000 * self.sample_width * self.channels

    @property
    def min_speech_frames(self) -> int:
        return max(0, _ceil_div(self.min_speech_ms, self.frame_ms))


def _ceil_div(value: int, divisor: int) -> int:
    return -(-value // divisor)


@dataclass(frozen=True)
class Utterance:
    pcm: bytes
    sample_rate: int
    sample_width: int
    channels: int

    @property
    def duration_seconds(self) -> float:
        if not self.pcm:
            return 0.0
        return len(self.pcm) / (self.sample_rate * self.sample_width * self.channels)


@dataclass(frozen=True)
class ListeningEvent:
    kind: str
    utterance: Utterance | None = None
    keyword: str | None = None


class KWSFrameAccumulator:
    """Convert VAD-sized input frames into independently sized KWS frames."""

    def __init__(self, frame_byte_count: int) -> None:
        if frame_byte_count <= 0:
            raise ValueError("frame_byte_count must be positive")
        self._frame_byte_count = frame_byte_count
        self._buffer = bytearray()

    def push(self, pcm_frame: bytes) -> list[bytes]:
        self._buffer.extend(pcm_frame)
        frames = []
        while len(self._buffer) >= self._frame_byte_count:
            frames.append(bytes(self._buffer[: self._frame_byte_count]))
            del self._buffer[: self._frame_byte_count]
        return frames


class VoiceActivityDetector(Protocol):
    def is_speech(self, pcm_frame: bytes, sample_rate: int) -> bool:
        ...


class WebRTCVoiceActivityDetector:
    def __init__(self, aggressiveness: int) -> None:
        if aggressiveness < 0 or aggressiveness > 3:
            raise ValueError("aggressiveness must be between 0 and 3.")

        import webrtcvad

        self._vad = webrtcvad.Vad(aggressiveness)

    def is_speech(self, pcm_frame: bytes, sample_rate: int) -> bool:
        return self._vad.is_speech(pcm_frame, sample_rate)


class UtteranceSegmenter:
    def __init__(self, detector: VoiceActivityDetector, settings: VADSettings) -> None:
        self._detector = detector
        self._settings = settings
        standby_buffer_frames = max(settings.pre_roll_frames, settings.start_trigger_frames)
        self._pre_roll: deque[bytes] = deque(maxlen=standby_buffer_frames)
        self._utterance_frames: list[bytes] = []
        self._voiced_frames = 0
        self._silence_frames = 0
        self._active_frames = 0
        self._in_speech = False

    @property
    def in_speech(self) -> bool:
        return self._in_speech

    def start_with_frames(self, frames: list[bytes]) -> list[ListeningEvent]:
        for frame in frames:
            if len(frame) != self._settings.frame_byte_count:
                raise ValueError(
                    f"Expected {self._settings.frame_byte_count} bytes per frame, "
                    f"got {len(frame)}."
                )

        self._in_speech = True
        self._silence_frames = 0
        self._voiced_frames = self._settings.start_trigger_frames
        self._utterance_frames = list(frames)
        self._pre_roll.clear()
        return [ListeningEvent(kind="speech_started")]

    def prepend_frames(self, frames: list[bytes]) -> None:
        for frame in frames:
            if len(frame) != self._settings.frame_byte_count:
                raise ValueError(
                    f"Expected {self._settings.frame_byte_count} bytes per frame, "
                    f"got {len(frame)}."
                )

        if not self._in_speech or not frames:
            return

        self._utterance_frames = list(frames) + self._utterance_frames

    def process_frame(self, pcm_frame: bytes) -> list[ListeningEvent]:
        if len(pcm_frame) != self._settings.frame_byte_count:
            raise ValueError(
                f"Expected {self._settings.frame_byte_count} bytes per frame, "
                f"got {len(pcm_frame)}."
            )

        is_speech = self._detector.is_speech(pcm_frame, self._settings.sample_rate)

        if not self._in_speech:
            return self._process_standby_frame(pcm_frame, is_speech)

        return self._process_active_frame(pcm_frame, is_speech)

    def _process_standby_frame(self, pcm_frame: bytes, is_speech: bool) -> list[ListeningEvent]:
        self._pre_roll.append(pcm_frame)

        if is_speech:
            self._voiced_frames += 1
        else:
            self._voiced_frames = 0

        if self._voiced_frames < self._settings.start_trigger_frames:
            return []

        self._in_speech = True
        self._silence_frames = 0
        self._utterance_frames = list(self._pre_roll)
        return [ListeningEvent(kind="speech_started")]

    def _process_active_frame(self, pcm_frame: bytes, is_speech: bool) -> list[ListeningEvent]:
        self._utterance_frames.append(pcm_frame)
        self._active_frames += 1

        if is_speech:
            self._silence_frames = 0
            return []

        self._silence_frames += 1
        if self._silence_frames < self._settings.end_silence_frames:
            return []

        utterance = Utterance(
            pcm=b"".join(self._utterance_frames),
            sample_rate=self._settings.sample_rate,
            sample_width=self._settings.sample_width,
            channels=self._settings.channels,
        )
        is_long_enough = (
            self._settings.min_speech_frames == 0
            or self._active_frames >= self._settings.min_speech_frames
        )
        self._reset()
        if not is_long_enough:
            return []
        return [ListeningEvent(kind="speech_ended", utterance=utterance)]

    def _reset(self) -> None:
        self._pre_roll.clear()
        self._utterance_frames = []
        self._voiced_frames = 0
        self._silence_frames = 0
        self._active_frames = 0
        self._in_speech = False


def microphone_events(
    settings: VADSettings,
    device: str | int | None = None,
    standby_timeout: float | None = None,
    wake_word_detector: WakeWordDetector | None = None,
    wake_ack_delay: float = 0.8,
    wake_buffer_ms: int = 1000,
    stop_event: threading.Event | None = None,
    on_audio_state=None,
) -> Iterator[ListeningEvent]:
    import time
    import sounddevice as sd

    audio_queue: queue.Queue[bytes] = queue.Queue()
    detector = WebRTCVoiceActivityDetector(settings.aggressiveness)
    segmenter = UtteranceSegmenter(detector, settings)
    wake_gate = WakeWordGate(wake_word_detector) if wake_word_detector is not None else None
    wake_detected = wake_gate is None
    if wake_gate is not None:
        # A listener is recreated after every conversation/standby transition.
        # Reset stateful KWS runtimes (notably Alibaba SoundConnect) at this
        # boundary so a previous conversation cannot poison the next wake.
        wake_gate.reset()
        logger.info("wake_detector_reset reason=listener_started")
    wake_ack_deadline: float | None = None
    wake_buffer: deque[bytes] = deque(maxlen=settings.frames_for_ms(wake_buffer_ms))
    pending_wake_frames: list[bytes] = []
    kws_accumulator = KWSFrameAccumulator(settings.kws_frame_byte_count)

    def callback(indata, _frames, _time, status) -> None:
        if status:
            logger.warning("audio_input_status %s", status)
        audio_queue.put(bytes(indata))

    opened = False
    def closed():
        if opened and on_audio_state is not None: on_audio_state(False)
    with ExitStack() as resources:
        resources.callback(closed)
        resources.enter_context(sd.RawInputStream(
        samplerate=settings.sample_rate,
        blocksize=settings.frame_samples,
        dtype="int16",
        channels=settings.channels,
        device=device,
        callback=callback,
        ))
        opened = True
        if on_audio_state is not None: on_audio_state(True)
        standby_start = time.monotonic()
        while True:
            if stop_event is not None and stop_event.is_set():
                break
            if wake_ack_deadline is not None and time.monotonic() >= wake_ack_deadline:
                wake_ack_deadline = None
                pending_wake_frames = []
                yield ListeningEvent(kind="wake_ack_requested")
                _drain_audio_queue(audio_queue)
                standby_start = time.monotonic()
                continue

            if wake_detected and not segmenter.in_speech and standby_timeout is not None:
                if (time.monotonic() - standby_start) >= standby_timeout:
                    yield ListeningEvent(kind="standby_timeout")
                    break

            try:
                pcm_frame = audio_queue.get(timeout=0.05)
            except queue.Empty:
                continue

            if not wake_detected and wake_gate is not None:
                wake_buffer.append(pcm_frame)
                hit = None
                for kws_frame in kws_accumulator.push(pcm_frame):
                    hit = wake_gate.process_frame(kws_frame, settings.sample_rate)
                    if hit is not None:
                        break
                if hit is None:
                    continue

                wake_detected = True
                wake_ack_deadline = time.monotonic() + max(0.0, wake_ack_delay)
                pending_wake_frames = list(wake_buffer)
                yield ListeningEvent(kind="wake_detected", keyword=hit.keyword)
                standby_start = time.monotonic()
                continue

            events = segmenter.process_frame(pcm_frame)
            if any(event.kind == "speech_started" for event in events):
                if pending_wake_frames:
                    segmenter.prepend_frames(pending_wake_frames)
                    pending_wake_frames = []
                wake_ack_deadline = None
            if segmenter.in_speech:
                standby_start = time.monotonic()

            yield from events


def list_input_devices() -> str:
    import sounddevice as sd

    return str(sd.query_devices())


def _drain_audio_queue(audio_queue: queue.Queue[bytes]) -> None:
    while True:
        try:
            audio_queue.get_nowait()
        except queue.Empty:
            return


def write_utterance_wav(path: Path, utterance: Utterance) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with wave.open(str(path), "wb") as wav_file:
        wav_file.setnchannels(utterance.channels)
        wav_file.setsampwidth(utterance.sample_width)
        wav_file.setframerate(utterance.sample_rate)
        wav_file.writeframes(utterance.pcm)
