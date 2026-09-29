from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
import tomllib
from typing import Any

from myagent.voice import VADSettings, WakeWordDetector


def load_cli_defaults(path: Path) -> dict[str, Any]:
    """Translate the unified TOML config into argparse destination names."""
    if not path.exists():
        return {}
    with path.open("rb") as config_file:
        data = tomllib.load(config_file)

    defaults: dict[str, Any] = {}

    def copy(section: str, mapping: dict[str, str]) -> None:
        values = data.get(section, {})
        if not isinstance(values, dict):
            raise ValueError(f"Config section [{section}] must be a table.")
        for source, destination in mapping.items():
            if source in values:
                defaults[destination] = values[source]

    copy("agent", {
        "timeout": "timeout", "continuous": "continuous", "max_turns": "max_turns",
        "reply_prefix": "reply_prefix", "brain": "brain", "device": "device",
        "output_dir": "output_dir",
    })
    copy("openclaw", {
        "url": "openclaw_url", "token": "openclaw_token", "model": "openclaw_model",
        "session": "openclaw_session", "timeout": "openclaw_timeout",
    })
    copy("taskbrain", {
        "url": "taskbrain_url", "token": "taskbrain_token", "model": "taskbrain_model",
        "reasoning_effort": "taskbrain_reasoning_effort", "timeout": "taskbrain_timeout",
        "mcp_command": "taskbrain_mcp_command", "mcp_timeout": "taskbrain_mcp_timeout",
        "search": "taskbrain_search", "search_token": "taskbrain_search_token",
        "search_timeout": "taskbrain_search_timeout", "tasks": "taskbrain_tasks",
        "max_workers": "taskbrain_max_workers", "codex_cwd": "taskbrain_codex_cwd",
        "codex_timeout": "taskbrain_codex_timeout", "memory": "taskbrain_memory",
        "memory_backend": "taskbrain_memory_backend", "memory_source": "taskbrain_memory_source",
        "user_id": "taskbrain_user_id", "trust_user_id": "taskbrain_trust_user_id",
        "embedding": "taskbrain_embedding", "embedding_device": "taskbrain_embedding_device",
        "speaker_recognition": "speaker_recognition", "speaker_profiles": "speaker_profiles",
        "speaker_model_dir": "speaker_model_dir", "speaker_threshold": "speaker_threshold",
    })
    copy("knowledge", {
        "enabled": "knowledge_enabled",
        "documents_root": "knowledge_documents_root",
        "metadata": "knowledge_metadata",
        "vectors": "knowledge_vectors",
        "queue": "knowledge_queue",
        "embedding": "knowledge_embedding",
        "embedding_device": "knowledge_embedding_device",
        "watcher_poll_interval": "knowledge_watcher_poll_interval",
        "indexing_max_attempts": "knowledge_indexing_max_attempts",
    })
    copy("voice", {
        "model": "model", "stt_provider": "stt_provider", "language": "language",
        "compute_type": "compute_type", "stt_device": "stt_device",
        "normalize_stt_audio": "normalize_stt_audio", "stt_target_peak": "stt_target_peak",
        "stt_min_peak": "stt_min_peak", "stt_max_gain": "stt_max_gain",
        "tts_voice": "tts_voice", "tts_rate": "tts_rate",
        "interruptible_tts": "interruptible_tts",
    })
    copy("wake", {
        "config": "wake_config", "ack": "wake_ack", "ack_delay": "wake_ack_delay",
        "buffer_ms": "wake_buffer_ms",
    })
    copy("vad", {
        "aggressiveness": "vad_aggressiveness", "frame_ms": "frame_ms",
        "start_trigger_ms": "start_trigger_ms", "end_silence_ms": "end_silence_ms",
        "pre_roll_ms": "pre_roll_ms",
    })
    copy("environment", {
        "location": "location",
        "location_helper": "location_helper",
        "external_ip_url": "external_ip_url",
        "timeout": "environment_timeout",
    })
    if "normalize_stt_audio" in defaults:
        defaults["no_normalize_stt_audio"] = not defaults.pop("normalize_stt_audio")
    if "interruptible_tts" in defaults:
        defaults["no_interruptible_tts"] = not defaults.pop("interruptible_tts")
    for key in (
        "output_dir", "taskbrain_tasks", "taskbrain_codex_cwd", "taskbrain_memory",
        "taskbrain_memory_source", "wake_config",
        "location_helper", "speaker_profiles", "speaker_model_dir",
        "knowledge_documents_root", "knowledge_metadata", "knowledge_vectors",
    ):
        if key in defaults and defaults[key] is not None:
            defaults[key] = Path(defaults[key])
    return defaults


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
    wake_keywords: tuple[str, ...] = ("麥芽糖", "麦芽糖")
    wake_ack_text: str | None = "我在"
    wake_ack_delay: float = 0.8
    wake_buffer_ms: int = 1000
    interruptible_tts: bool = True
    normalize_stt_audio: bool = True
    stt_target_peak: int = 12000
    stt_min_peak: int = 6000
    stt_max_gain: float = 4.0
