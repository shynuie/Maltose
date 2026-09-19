from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

from myagent.voice import VADSettings, WakeWordDetector


@dataclass(frozen=True)
class AgentConfig:
    standby_timeout: float = 10.0
    continuous: bool = False
    max_turns: int | None = None
    vad_settings: VADSettings = field(default_factory=VADSettings)
    device: str | int | None = None
    whisper_model: str = "small"
    stt_provider: str = "qwen3-asr-0.6b"
    whisper_language: str = "zh"
    whisper_compute_type: str = "int8"
    stt_device: str = "cpu"
    tts_voice: str | None = None
    tts_rate: int | None = None
    output_dir: Path = field(default_factory=lambda: Path("recordings"))
    wake_word_detector: WakeWordDetector | None = None
    wake_ack_text: str | None = None
    wake_ack_delay: float = 0.8
    wake_buffer_ms: int = 1000
    normalize_stt_audio: bool = True
    stt_target_peak: int = 12000
    stt_min_peak: int = 6000
    stt_max_gain: float = 4.0
