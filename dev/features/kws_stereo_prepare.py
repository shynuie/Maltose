"""Create duplicated-channel WAV copies for ModelScope KWS fixtures.

This utility is for raw negative/test audio only. It must not be used on
force-align output, whose second channel contains labels.
"""

from __future__ import annotations

import argparse
from pathlib import Path

import numpy as np
from scipy.io import wavfile


def convert(
    source: Path,
    destination: Path,
    channels: int = 2,
    silent_last_channel: bool = False,
) -> int:
    if channels < 1:
        raise ValueError("channels must be positive")
    destination.mkdir(parents=True, exist_ok=True)
    converted = 0
    for input_path in sorted(source.rglob("*.wav")):
        if input_path.name.startswith("._"):
            continue
        try:
            rate, samples = wavfile.read(input_path)
        except ValueError:
            # Some legacy recordings carry a .wav suffix but contain raw
            # 16 kHz mono PCM. Normalize them to a real WAV on output.
            rate = 16000
            samples = np.fromfile(input_path, dtype=np.int16)
        if samples.ndim == 1:
            samples = np.repeat(samples[:, None], channels, axis=1)
        elif samples.ndim != 2 or samples.shape[1] != channels:
            raise ValueError(
                f"expected mono or {channels}-channel WAV: {input_path}")
        if silent_last_channel:
            samples = samples.copy()
            samples[:, -1] = 0
        wavfile.write(destination / input_path.name, rate, samples)
        converted += 1
    return converted


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("source", type=Path)
    parser.add_argument("destination", type=Path)
    parser.add_argument("--channels", type=int, default=2)
    parser.add_argument("--silent-last-channel", action="store_true")
    args = parser.parse_args()
    print(convert(
        args.source,
        args.destination,
        args.channels,
        args.silent_last_channel,
    ))


if __name__ == "__main__":
    main()
