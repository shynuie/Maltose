from __future__ import annotations

import tempfile
import wave
from dataclasses import dataclass
from pathlib import Path


MANDARIN_PUNCTUATION = str.maketrans(
    {
        ",": "，",
        ".": "。",
        "?": "？",
        "!": "！",
        ":": "：",
        ";": "；",
    }
)


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
            normalized_segment_text = normalize_mandarin_transcript(segment.text)
            raw_text_parts.append(normalized_segment_text)
            segment_values.append(
                STTSegment(
                    start=segment.start,
                    end=segment.end,
                    text=normalized_segment_text.strip(),
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


class FunASRNanoSTT:
    """Speech-to-text provider backed by Fun-ASR-Nano."""

    def __init__(
        self,
        model: str = "FunAudioLLM/Fun-ASR-Nano-2512",
        device: str = "cpu",
    ) -> None:
        self.model_name = model
        self.device = device
        self._model = None

    @property
    def model(self):
        if self._model is None:
            try:
                from funasr import AutoModel
            except ImportError as exc:
                raise RuntimeError(
                    "Fun-ASR-Nano requires the 'funasr' optional dependency. "
                    "Install it with: uv sync --extra funasr"
                ) from exc

            self._model = AutoModel(
                model=self.model_name,
                device=self.device,
                trust_remote_code=True,
                disable_update=True,
            )
        return self._model

    def transcribe(self, request: STTRequest) -> STTResult:
        audio_path = request.audio_path.expanduser()
        if not audio_path.exists():
            raise FileNotFoundError(f"Audio file not found: {audio_path}")

        results = self.model.generate(input=str(audio_path))
        text = ""
        if results:
            text = normalize_mandarin_transcript(str(results[0].get("text", ""))).strip()

        duration = None
        if results:
            raw_duration = results[0].get("duration")
            if isinstance(raw_duration, (int, float)):
                duration = float(raw_duration)

        return STTResult(
            text=text,
            language=request.language,
            duration=duration,
            segments=(
                (STTSegment(start=0.0, end=duration or 0.0, text=text),)
                if text
                else ()
            ),
        )


class Qwen3ASRSTT:
    """Speech-to-text provider backed by Qwen3-ASR-0.6B."""

    def __init__(
        self,
        model: str = "Qwen/Qwen3-ASR-0.6B",
        device: str = "cpu",
    ) -> None:
        self.model_name = model
        self.device = device
        self._model = None

    @property
    def model(self):
        if self._model is None:
            try:
                import torch
                from qwen_asr import Qwen3ASRModel
            except ImportError as exc:
                raise RuntimeError(
                    "Qwen3-ASR requires the 'qwen-asr' optional dependency. "
                    "Install it with: uv sync --extra qwen-asr"
                ) from exc

            dtype = torch.float16 if self.device == "mps" else torch.float32
            self._model = Qwen3ASRModel.from_pretrained(
                self.model_name,
                dtype=dtype,
                device_map=self.device,
                max_inference_batch_size=1,
                max_new_tokens=256,
            )
        return self._model

    def transcribe(self, request: STTRequest) -> STTResult:
        audio_path = request.audio_path.expanduser()
        if not audio_path.exists():
            raise FileNotFoundError(f"Audio file not found: {audio_path}")

        language = {"zh": "Chinese", "en": "English"}.get(request.language, request.language)
        result = self.model.transcribe(audio=str(audio_path), language=language)[0]
        text = normalize_mandarin_transcript(str(result.text)).strip()
        return STTResult(
            text=text,
            language=getattr(result, "language", request.language),
            duration=None,
            segments=(STTSegment(start=0.0, end=0.0, text=text),) if text else (),
        )

    def warmup(self) -> None:
        """Load the model and execute one short silent inference."""
        with tempfile.NamedTemporaryFile(suffix=".wav") as audio:
            with wave.open(audio.name, "wb") as wav_file:
                wav_file.setnchannels(1)
                wav_file.setsampwidth(2)
                wav_file.setframerate(16000)
                wav_file.writeframes(b"\0" * (16000 * 2 // 2))

            self.transcribe(
                STTRequest(
                    audio_path=Path(audio.name),
                    language="zh",
                )
            )


def create_stt_provider(
    provider: str = "faster-whisper",
    model: str = "small",
    device: str = "cpu",
    compute_type: str = "int8",
):
    if provider == "faster-whisper":
        return FasterWhisperSTT()
    if provider == "fun-asr-nano":
        if model == "small":
            model = "FunAudioLLM/Fun-ASR-Nano-2512"
        return FunASRNanoSTT(model=model, device=device)
    if provider == "qwen3-asr-0.6b":
        if model == "small":
            model = "Qwen/Qwen3-ASR-0.6B"
        return Qwen3ASRSTT(model=model, device=device)
    raise ValueError(f"Unsupported STT provider: {provider}")


def normalize_mandarin_transcript(text: str) -> str:
    return text.translate(MANDARIN_PUNCTUATION)
