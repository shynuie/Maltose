"""Inspect the audio and label channels emitted by ModelScope force_align."""

from __future__ import annotations

import argparse
from pathlib import Path

import numpy as np
from scipy.io import wavfile


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("path", type=Path)
    args = parser.parse_args()

    rate, data = wavfile.read(args.path)
    if data.ndim != 2 or data.shape[1] != 2:
        raise SystemExit(f"expected stereo audio+label WAV, got shape={data.shape}")

    labels = data[:, 1]
    values, counts = np.unique(labels, return_counts=True)
    print(f"rate={rate} shape={data.shape}")
    print(f"label_min={labels.min()} label_max={labels.max()} unique={len(values)}")
    for value, count in zip(values.tolist(), counts.tolist()):
        if value != 0:
            print(f"label={value} samples={count}")


if __name__ == "__main__":
    main()
