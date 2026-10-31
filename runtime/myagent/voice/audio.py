from __future__ import annotations

import audioop
from dataclasses import dataclass
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from myagent.voice.listening import Utterance


@dataclass(frozen=True)
class AudioStats:
    duration_seconds: float
    rms: int
    peak: int


@dataclass(frozen=True)
class NormalizationResult:
    utterance: "Utterance"
    before: AudioStats
    after: AudioStats
    gain: float


def measure_utterance(utterance: "Utterance") -> AudioStats:
    if not utterance.pcm:
        return AudioStats(duration_seconds=0.0, rms=0, peak=0)

    return AudioStats(
        duration_seconds=utterance.duration_seconds,
        rms=audioop.rms(utterance.pcm, utterance.sample_width),
        peak=audioop.max(utterance.pcm, utterance.sample_width),
    )


def normalize_utterance_peak(
    utterance: "Utterance",
    target_peak: int = 12000,
    min_peak: int = 6000,
    max_gain: float = 4.0,
) -> NormalizationResult:
    before = measure_utterance(utterance)
    gain = _normalization_gain(
        peak=before.peak,
        target_peak=target_peak,
        min_peak=min_peak,
        max_gain=max_gain,
    )

    if gain == 1.0:
        return NormalizationResult(
            utterance=utterance,
            before=before,
            after=before,
            gain=gain,
        )

    from myagent.voice.listening import Utterance

    normalized = Utterance(
        pcm=audioop.mul(utterance.pcm, utterance.sample_width, gain),
        sample_rate=utterance.sample_rate,
        sample_width=utterance.sample_width,
        channels=utterance.channels,
    )
    return NormalizationResult(
        utterance=normalized,
        before=before,
        after=measure_utterance(normalized),
        gain=gain,
    )


def normalize_pcm_peak(
    pcm: bytes,
    sample_width: int = 2,
    target_peak: int = 12000,
    min_peak: int = 6000,
    max_gain: float = 4.0,
) -> tuple[bytes, float, int, int]:
    peak = audioop.max(pcm, sample_width) if pcm else 0
    gain = _normalization_gain(
        peak=peak,
        target_peak=target_peak,
        min_peak=min_peak,
        max_gain=max_gain,
    )
    if gain == 1.0:
        return pcm, gain, peak, peak

    normalized = audioop.mul(pcm, sample_width, gain)
    return normalized, gain, peak, audioop.max(normalized, sample_width)


def _normalization_gain(
    peak: int,
    target_peak: int,
    min_peak: int,
    max_gain: float,
) -> float:
    if peak <= 0 or peak >= min_peak:
        return 1.0

    gain = target_peak / peak
    return max(1.0, min(gain, max_gain))
