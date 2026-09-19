"""Voice features for MyAgent."""

from .stt import FasterWhisperSTT, STTRequest, STTResult, STTSegment
from .tts import MacOSSayTTS, TTSRequest

__all__ = [
    "FasterWhisperSTT",
    "MacOSSayTTS",
    "STTRequest",
    "STTResult",
    "STTSegment",
    "TTSRequest",
]
