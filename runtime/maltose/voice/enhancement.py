from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class SpectralGateConfig:
    noise_floor_rms: int = 120
    strength: float = 1.0
    gain_floor: float = 0.20
    noise_adaptation: float = 0.05


class SpectralNoiseSuppressor:
    """Lightweight stateful spectral attenuation for offline/streaming experiments."""

    def __init__(self, sample_rate: int = 16000, config: SpectralGateConfig | None = None) -> None:
        if sample_rate <= 0:
            raise ValueError("sample_rate must be positive")
        self.sample_rate = sample_rate
        self.config = config or SpectralGateConfig()
        if not 0.0 <= self.config.gain_floor <= 1.0:
            raise ValueError("gain_floor must be between 0 and 1")
        if not 0.0 < self.config.noise_adaptation <= 1.0:
            raise ValueError("noise_adaptation must be between 0 and 1")
        self._noise_magnitude = None

    def process(self, pcm_frame: bytes) -> bytes:
        import audioop
        import numpy as np

        if not pcm_frame:
            return pcm_frame
        samples = np.frombuffer(pcm_frame, dtype=np.int16).astype(np.float32)
        magnitude = np.abs(np.fft.rfft(samples))
        if self._noise_magnitude is None or len(self._noise_magnitude) != len(magnitude):
            self._noise_magnitude = magnitude.copy()
            return pcm_frame

        rms = audioop.rms(pcm_frame, 2)
        if rms <= self.config.noise_floor_rms:
            rate = self.config.noise_adaptation
            self._noise_magnitude = (
                (1.0 - rate) * self._noise_magnitude + rate * magnitude
            )

        ratio = self._noise_magnitude / (magnitude + 1e-6)
        attenuation = np.clip(
            1.0 - self.config.strength * ratio,
            self.config.gain_floor,
            1.0,
        )
        enhanced = np.fft.irfft(np.fft.rfft(samples) * attenuation, n=len(samples))
        enhanced = np.clip(np.rint(enhanced), -32768, 32767).astype(np.int16)
        return enhanced.tobytes()

    def reset(self) -> None:
        self._noise_magnitude = None
