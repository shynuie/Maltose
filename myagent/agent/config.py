from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

from myagent.voice import VADSettings


@dataclass(frozen=True)
class AgentConfig:
    standby_timeout: float = 10.0
    continuous: bool = False
    max_turns: int | None = None
    vad_settings: VADSettings = field(default_factory=VADSettings)
    device: str | int | None = None
    whisper_model: str = "small"
    whisper_language: str = "zh"
    whisper_compute_type: str = "int8"
    tts_voice: str | None = None
    tts_rate: int | None = None
    output_dir: Path = field(default_factory=lambda: Path("recordings"))
