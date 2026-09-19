"""Voice features for MyAgent."""

from .listening import ListeningEvent, Utterance, UtteranceSegmenter, VADSettings
from .stt import (
    FasterWhisperSTT,
    STTRequest,
    STTResult,
    STTSegment,
    normalize_mandarin_transcript,
)
from .tts import MacOSSayTTS, TTSRequest

__all__ = [
    "FasterWhisperSTT",
    "ListeningEvent",
    "MacOSSayTTS",
    "STTRequest",
    "STTResult",
    "STTSegment",
    "TTSRequest",
    "Utterance",
    "UtteranceSegmenter",
    "VADSettings",
    "normalize_mandarin_transcript",
]
