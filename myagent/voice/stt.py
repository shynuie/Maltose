from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class STTRequest:
    audio_path: Path
    model_size: str = "small"
    language: str = "zh"
    device: str = "cpu"
    compute_type: str = "int8"
    beam_size: int = 5


@dataclass(frozen=True)
class STTSegment:
    start: float
    end: float
    text: str


@dataclass(frozen=True)
class STTResult:
    text: str
    language: str | None
    duration: float | None
    segments: tuple[STTSegment, ...]


class FasterWhisperSTT:
    """Speech-to-text provider backed by faster-whisper."""

    def transcribe(self, request: STTRequest) -> STTResult:
        audio_path = request.audio_path.expanduser()
        if not audio_path.exists():
            raise FileNotFoundError(f"Audio file not found: {audio_path}")

        if request.beam_size < 1:
            raise ValueError("beam_size must be at least 1.")

        from faster_whisper import WhisperModel

        model = WhisperModel(
            request.model_size,
            device=request.device,
            compute_type=request.compute_type,
        )
        segments_iter, info = model.transcribe(
            str(audio_path),
            language=request.language,
            beam_size=request.beam_size,
        )

        segment_values = []
        raw_text_parts = []
        for segment in segments_iter:
            raw_text_parts.append(segment.text)
            segment_values.append(
                STTSegment(
                    start=segment.start,
                    end=segment.end,
                    text=segment.text.strip(),
                )
            )

        segments = tuple(segment_values)
        text = "".join(raw_text_parts).strip()

        return STTResult(
            text=text,
            language=getattr(info, "language", None),
            duration=getattr(info, "duration", None),
            segments=segments,
        )
