"""Voice features for MyAgent."""

from .listening import (
    ListeningEvent,
    Utterance,
    UtteranceSegmenter,
    VADSettings,
    microphone_events,
    write_utterance_wav,
)
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
    "microphone_events",
    "normalize_mandarin_transcript",
    "write_utterance_wav",
]
