from __future__ import annotations

import tomllib
from dataclasses import dataclass
from pathlib import Path
from typing import Protocol

from myagent.voice.audio import normalize_pcm_peak


@dataclass(frozen=True)
class WakeWordHit:
    keyword: str


class WakeWordDetector(Protocol):
    def process_frame(self, pcm_frame: bytes, sample_rate: int) -> WakeWordHit | None:
        ...

    def reset(self) -> None:
        ...


@dataclass(frozen=True)
class SherpaOnnxKWSConfig:
    tokens: Path
    encoder: Path
    decoder: Path
    joiner: Path
    keywords_file: Path
    num_threads: int = 1
    provider: str = "cpu"
    max_active_paths: int = 4
    keywords_score: float = 1.0
    keywords_threshold: float = 0.25
    num_trailing_blanks: int = 1


@dataclass(frozen=True)
class WakeWordConfig:
    enabled: bool = True
    provider: str = "sherpa-onnx"
    sherpa_onnx: SherpaOnnxKWSConfig | None = None
    normalize_audio: bool = True
    target_peak: int = 12000
    min_peak: int = 6000
    max_gain: float = 4.0


class WakeWordGate:
    def __init__(self, detector: WakeWordDetector) -> None:
        self._detector = detector

    def process_frame(self, pcm_frame: bytes, sample_rate: int) -> WakeWordHit | None:
        hit = self._detector.process_frame(pcm_frame, sample_rate)
        if hit is not None:
            self._detector.reset()
        return hit


class GainWakeWordDetector:
    def __init__(
        self,
        detector: WakeWordDetector,
        target_peak: int = 12000,
        min_peak: int = 6000,
        max_gain: float = 4.0,
    ) -> None:
        self._detector = detector
        self._target_peak = target_peak
        self._min_peak = min_peak
        self._max_gain = max_gain

    def process_frame(self, pcm_frame: bytes, sample_rate: int) -> WakeWordHit | None:
        normalized_frame, _gain, _before_peak, _after_peak = normalize_pcm_peak(
            pcm_frame,
            target_peak=self._target_peak,
            min_peak=self._min_peak,
            max_gain=self._max_gain,
        )
        return self._detector.process_frame(normalized_frame, sample_rate)

    def reset(self) -> None:
        self._detector.reset()


class SherpaOnnxKeywordSpotter:
    def __init__(self, config: SherpaOnnxKWSConfig) -> None:
        self._config = config

        import sherpa_onnx

        self._keyword_spotter = sherpa_onnx.KeywordSpotter(
            tokens=str(config.tokens),
            encoder=str(config.encoder),
            decoder=str(config.decoder),
            joiner=str(config.joiner),
            keywords_file=str(config.keywords_file),
            num_threads=config.num_threads,
            provider=config.provider,
            max_active_paths=config.max_active_paths,
            keywords_score=config.keywords_score,
            keywords_threshold=config.keywords_threshold,
            num_trailing_blanks=config.num_trailing_blanks,
        )
        self._stream = self._keyword_spotter.create_stream()

    def process_frame(self, pcm_frame: bytes, sample_rate: int) -> WakeWordHit | None:
        import numpy as np

        samples = np.frombuffer(pcm_frame, dtype=np.int16).astype(np.float32) / 32768.0
        self._stream.accept_waveform(sample_rate, samples)

        while self._keyword_spotter.is_ready(self._stream):
            self._keyword_spotter.decode_stream(self._stream)

        keyword = self._keyword_spotter.get_result(self._stream)
        if not keyword:
            return None

        return WakeWordHit(keyword=keyword)

    def reset(self) -> None:
        self._keyword_spotter.reset_stream(self._stream)


def create_wake_word_detector(config: WakeWordConfig) -> WakeWordDetector | None:
    if not config.enabled:
        return None
    if config.provider != "sherpa-onnx":
        raise ValueError(f"Unsupported wake word provider: {config.provider}")
    if config.sherpa_onnx is None:
        raise ValueError("sherpa-onnx wake config is required.")
    detector: WakeWordDetector = SherpaOnnxKeywordSpotter(config.sherpa_onnx)
    if not config.normalize_audio:
        return detector

    return GainWakeWordDetector(
        detector,
        target_peak=config.target_peak,
        min_peak=config.min_peak,
        max_gain=config.max_gain,
    )


def load_wake_word_config(path: Path) -> WakeWordConfig:
    with path.open("rb") as config_file:
        data = tomllib.load(config_file)

    wake_data = data.get("wake", data)
    provider = wake_data.get("provider", "sherpa-onnx")

    sherpa_data = wake_data.get("sherpa_onnx", wake_data.get("sherpa-onnx", wake_data))
    sherpa_config = None
    if provider == "sherpa-onnx":
        sherpa_config = SherpaOnnxKWSConfig(
            tokens=_resolve_config_path(path, sherpa_data["tokens"]),
            encoder=_resolve_config_path(path, sherpa_data["encoder"]),
            decoder=_resolve_config_path(path, sherpa_data["decoder"]),
            joiner=_resolve_config_path(path, sherpa_data["joiner"]),
            keywords_file=_resolve_config_path(path, sherpa_data["keywords_file"]),
            num_threads=int(sherpa_data.get("num_threads", 1)),
            provider=str(sherpa_data.get("provider", "cpu")),
            max_active_paths=int(sherpa_data.get("max_active_paths", 4)),
            keywords_score=float(sherpa_data.get("keywords_score", 1.0)),
            keywords_threshold=float(sherpa_data.get("keywords_threshold", 0.25)),
            num_trailing_blanks=int(sherpa_data.get("num_trailing_blanks", 1)),
        )

    return WakeWordConfig(
        enabled=bool(wake_data.get("enabled", True)),
        provider=provider,
        sherpa_onnx=sherpa_config,
        normalize_audio=bool(wake_data.get("normalize_audio", True)),
        target_peak=int(wake_data.get("target_peak", 12000)),
        min_peak=int(wake_data.get("min_peak", 6000)),
        max_gain=float(wake_data.get("max_gain", 4.0)),
    )


def _resolve_config_path(config_path: Path, value: str) -> Path:
    path = Path(value).expanduser()
    if path.is_absolute():
        return path
    return config_path.parent / path
