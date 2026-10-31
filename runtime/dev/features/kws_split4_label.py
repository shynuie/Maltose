"""Convert official three-state alignment labels into validated split4 labels."""

from __future__ import annotations

import argparse
from pathlib import Path

import numpy as np
from scipy.io import wavfile


def convert(source_dirs: list[Path], destination: Path, manifest: Path) -> int:
    destination.mkdir(parents=True, exist_ok=True)
    inputs = sorted({path for directory in source_dirs for path in directory.glob("*.wav")})
    if not inputs:
        raise SystemExit("no alignment WAV files found")
    output_paths: list[Path] = []
    for source in inputs:
        rate, samples = wavfile.read(source)
        if samples.ndim != 2 or samples.shape[1] != 2:
            raise ValueError(f"expected stereo alignment WAV: {source}")
        labels = samples[:, 1]
        positions = np.flatnonzero(labels == 983)
        if len(positions) < 2:
            raise ValueError(f"cannot split final label: {source}")
        converted = samples.copy()
        converted[positions[len(positions) // 2 :], 1] = 1310
        output = destination / source.name
        wavfile.write(output, rate, converted)
        output_paths.append(output)
    manifest.write_text("".join(f"/workspace/data/{path.relative_to(manifest.parents[4])}\n" for path in output_paths))
    print(f"converted={len(output_paths)}")
    return len(output_paths)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("source", nargs="+", type=Path)
    parser.add_argument("--destination", required=True, type=Path)
    parser.add_argument("--manifest", required=True, type=Path)
    args = parser.parse_args()
    convert(args.source, args.destination, args.manifest)


if __name__ == "__main__":
    main()
