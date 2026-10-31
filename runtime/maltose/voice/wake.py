from __future__ import annotations

import logging
import tomllib
from dataclasses import dataclass, replace
from pathlib import Path
from typing import Protocol

from maltose.voice.audio import normalize_pcm_peak
from maltose.voice.enhancement import SpectralGateConfig, SpectralNoiseSuppressor


logger = logging.getLogger(__name__)


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
class AlibabaKWSConfig:
    model_dir: Path
    python: Path


@dataclass(frozen=True)
class WakeWordConfig:
    enabled: bool = True
    provider: str = "sherpa-onnx"
    sherpa_onnx: SherpaOnnxKWSConfig | None = None
    alibaba: AlibabaKWSConfig | None = None
    fallback_config: Path | None = None
    normalize_audio: bool = True
    normalization_mode: str = "peak"
    target_peak: int = 12000
    min_peak: int = 6000
    max_gain: float = 4.0
    rms_target: int = 3000
    rms_noise_floor: int = 80
    rms_attack: float = 0.45
    rms_release: float = 0.12
    highpass_cutoff_hz: float = 80.0


class WakeWordGate:
    def __init__(self, detector: WakeWordDetector) -> None:
        self._detector = detector

    def process_frame(self, pcm_frame: bytes, sample_rate: int) -> WakeWordHit | None:
        hit = self._detector.process_frame(pcm_frame, sample_rate)
        if hit is not None:
            self._detector.reset()
        return hit

    def reset(self) -> None:
        """Start a fresh wake-listening cycle without replacing the detector."""
        self._detector.reset()


class FallbackWakeWordDetector:
    """Switch to a local fallback detector after worker failure."""

    def __init__(self, primary: WakeWordDetector, fallback: WakeWordDetector) -> None:
        self._primary = primary
        self._fallback = fallback
        self._using_fallback = False

    def process_frame(self, pcm_frame: bytes, sample_rate: int) -> WakeWordHit | None:
        if self._using_fallback:
            return self._fallback.process_frame(pcm_frame, sample_rate)
        try:
            return self._primary.process_frame(pcm_frame, sample_rate)
        except Exception as exc:
            logger.exception("wake_primary_failed_using_fallback error=%s", exc)
            self._using_fallback = True
            close = getattr(self._primary, "close", None)
            if callable(close):
                close()
            return self._fallback.process_frame(pcm_frame, sample_rate)

    def reset(self) -> None:
        if self._using_fallback:
            self._fallback.reset()
        else:
            self._primary.reset()


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


class SmoothRMSGainWakeWordDetector:
    """Apply stateful digital gain based on short-term RMS level."""

    def __init__(
        self,
        detector: WakeWordDetector,
        target_rms: int = 3000,
        noise_floor: int = 80,
        max_gain: float = 4.0,
        attack: float = 0.45,
        release: float = 0.12,
    ) -> None:
        if target_rms <= 0 or noise_floor < 0:
            raise ValueError("target_rms must be positive and noise_floor non-negative")
        if max_gain < 1.0:
            raise ValueError("max_gain must be at least 1.0")
        if not 0.0 < attack <= 1.0 or not 0.0 < release <= 1.0:
            raise ValueError("attack and release must be between 0 and 1")
        self._detector = detector
        self._target_rms = target_rms
        self._noise_floor = noise_floor
        self._max_gain = max_gain
        self._attack = attack
        self._release = release
        self._gain = 1.0

    @property
    def gain(self) -> float:
        return self._gain

    def process_frame(self, pcm_frame: bytes, sample_rate: int) -> WakeWordHit | None:
        import audioop

        rms = audioop.rms(pcm_frame, 2) if pcm_frame else 0
        desired_gain = 1.0
        if rms > self._noise_floor:
            desired_gain = min(self._max_gain, max(1.0, self._target_rms / rms))
        smoothing = self._attack if desired_gain > self._gain else self._release
        self._gain += (desired_gain - self._gain) * smoothing
        processed = (
            audioop.mul(pcm_frame, 2, self._gain)
            if self._gain != 1.0
            else pcm_frame
        )
        return self._detector.process_frame(processed, sample_rate)

    def reset(self) -> None:
        self._gain = 1.0
        self._detector.reset()


class HighPassWakeWordDetector:
    """Remove DC and low-frequency energy before passing audio downstream."""

    def __init__(
        self,
        detector: WakeWordDetector,
        sample_rate: int = 16000,
        cutoff_hz: float = 80.0,
    ) -> None:
        if sample_rate <= 0 or cutoff_hz <= 0 or cutoff_hz >= sample_rate / 2:
            raise ValueError("cutoff_hz must be between 0 and Nyquist frequency")
        self._detector = detector
        rc = 1.0 / (2.0 * 3.141592653589793 * cutoff_hz)
        self._alpha = rc / (rc + 1.0 / sample_rate)
        self._previous_input = 0.0
        self._previous_output = 0.0

    def process_frame(self, pcm_frame: bytes, sample_rate: int) -> WakeWordHit | None:
        import array

        samples = array.array("h")
        samples.frombytes(pcm_frame)
        for index, sample in enumerate(samples):
            output = self._alpha * (
                self._previous_output + float(sample) - self._previous_input
            )
            self._previous_input = float(sample)
            self._previous_output = output
            samples[index] = max(-32768, min(32767, int(round(output))))
        return self._detector.process_frame(samples.tobytes(), sample_rate)

    def reset(self) -> None:
        self._previous_input = 0.0
        self._previous_output = 0.0
        self._detector.reset()


class SpectralGateWakeWordDetector:
    def __init__(
        self,
        detector: WakeWordDetector,
        sample_rate: int = 16000,
        config: SpectralGateConfig | None = None,
    ) -> None:
        self._detector = detector
        self._suppressor = SpectralNoiseSuppressor(sample_rate=sample_rate, config=config)

    def process_frame(self, pcm_frame: bytes, sample_rate: int) -> WakeWordHit | None:
        enhanced = self._suppressor.process(pcm_frame)
        return self._detector.process_frame(enhanced, sample_rate)

    def reset(self) -> None:
        self._suppressor.reset()
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
    if config.provider == "alibaba-modelscope":
        if config.alibaba is None:
            raise ValueError("Alibaba KWS config is required.")
        from maltose.voice.alibaba_kws import AlibabaKWSDetector

        detector: WakeWordDetector = AlibabaKWSDetector(
            config.alibaba.model_dir,
            python=config.alibaba.python,
        )
        if config.fallback_config is not None:
            fallback_config = load_wake_word_config(config.fallback_config)
            fallback_config = replace(fallback_config, normalize_audio=False)
            fallback = create_wake_word_detector(fallback_config)
            if fallback is None:
                raise ValueError("Alibaba KWS fallback config is disabled")
            detector = FallbackWakeWordDetector(detector, fallback)
    elif config.provider == "sherpa-onnx":
        if config.sherpa_onnx is None:
            raise ValueError("sherpa-onnx wake config is required.")
        detector = SherpaOnnxKeywordSpotter(config.sherpa_onnx)
    else:
        raise ValueError(f"Unsupported wake word provider: {config.provider}")

    if not config.normalize_audio or config.normalization_mode == "none":
        return detector

    if config.normalization_mode == "spectral-gate":
        return SpectralGateWakeWordDetector(detector)
    if config.normalization_mode in ("smooth-rms", "highpass-smooth-rms"):
        smoothed: WakeWordDetector = SmoothRMSGainWakeWordDetector(
            detector,
            target_rms=config.rms_target,
            noise_floor=config.rms_noise_floor,
            max_gain=config.max_gain,
            attack=config.rms_attack,
            release=config.rms_release,
        )
        if config.normalization_mode == "highpass-smooth-rms":
            return HighPassWakeWordDetector(
                smoothed,
                cutoff_hz=config.highpass_cutoff_hz,
            )
        return smoothed
    if config.normalization_mode != "peak":
        raise ValueError(f"Unsupported wake normalization mode: {config.normalization_mode}")

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
    alibaba_config = None
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
    elif provider == "alibaba-modelscope":
        alibaba_data = wake_data.get("alibaba", wake_data)
        alibaba_config = AlibabaKWSConfig(
            model_dir=_resolve_config_path(path, alibaba_data["model_dir"]),
            python=_resolve_python_path(path, alibaba_data.get("python", "python3.10")),
        )

    return WakeWordConfig(
        enabled=bool(wake_data.get("enabled", True)),
        provider=provider,
        sherpa_onnx=sherpa_config,
        alibaba=alibaba_config,
        fallback_config=(
            _resolve_config_path(path, wake_data["fallback_config"])
            if wake_data.get("fallback_config")
            else None
        ),
        normalize_audio=bool(wake_data.get("normalize_audio", True)),
        normalization_mode=str(wake_data.get("normalization_mode", "peak")),
        target_peak=int(wake_data.get("target_peak", 12000)),
        min_peak=int(wake_data.get("min_peak", 6000)),
        max_gain=float(wake_data.get("max_gain", 4.0)),
        rms_target=int(wake_data.get("rms_target", 3000)),
        rms_noise_floor=int(wake_data.get("rms_noise_floor", 80)),
        rms_attack=float(wake_data.get("rms_attack", 0.45)),
        rms_release=float(wake_data.get("rms_release", 0.12)),
        highpass_cutoff_hz=float(wake_data.get("highpass_cutoff_hz", 80.0)),
    )


def _resolve_config_path(config_path: Path, value: str) -> Path:
    path = Path(value).expanduser()
    if path.is_absolute():
        return path
    return config_path.parent / path


def _resolve_python_path(config_path: Path, value: str) -> Path:
    # Bare command names retain PATH lookup; explicit relative paths belong to the config.
    path = Path(value).expanduser()
    if path.is_absolute() or ("/" not in value and "\\" not in value):
        return path
    # Resolving the final symlink would bypass the venv and run its base Python.
    return (config_path.parent / path).absolute()
