from __future__ import annotations

import argparse
import json
import math
import random
import wave
from array import array
from datetime import datetime
from pathlib import Path


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Mix KWS positive WAVs with background noise.")
    parser.add_argument("--positive-dir", type=Path, required=True)
    parser.add_argument("--noise-dir", type=Path, required=True)
    parser.add_argument("--output-dir", type=Path, required=True)
    parser.add_argument("--snr", type=float, action="append", dest="snrs", required=True)
    parser.add_argument("--seed", type=int, default=20260930)
    parser.add_argument("--max-positive", type=int)
    return parser


def main() -> None:
    args = build_parser().parse_args()
    positives = sorted(args.positive_dir.rglob("*.wav"))
    noises = sorted(args.noise_dir.rglob("*.wav"))
    if args.max_positive is not None:
        positives = positives[: args.max_positive]
    if not positives or not noises:
        raise ValueError("Both input directories must contain WAV files")

    args.output_dir.mkdir(parents=True, exist_ok=True)
    metadata_path = args.output_dir / "metadata.jsonl"
    rng = random.Random(args.seed)
    records = []
    for positive_index, positive_path in enumerate(positives, start=1):
        sample_rate, signal = read_wav(positive_path)
        for snr in args.snrs:
            noise_path = noises[rng.randrange(len(noises))]
            noise_rate, noise = read_wav(noise_path)
            if noise_rate != sample_rate:
                raise ValueError(f"Sample rate mismatch: {noise_path}")
            mixed = mix(signal, noise, snr_db=snr)
            output_path = args.output_dir / (
                f"mixed-{positive_index:04d}-snr{format_snr(snr)}db.wav"
            )
            write_wav(output_path, sample_rate, mixed)
            records.append(
                {
                    "path": str(output_path),
                    "kind": "positive",
                    "keyword": "麥芽糖",
                    "source_positive": str(positive_path.resolve()),
                    "source_noise": str(noise_path.resolve()),
                    "snr_db": snr,
                    "sample_rate": sample_rate,
                    "duration_seconds": len(mixed) / sample_rate,
                    "recorded_at": datetime.now().astimezone().isoformat(),
                }
            )
    with metadata_path.open("w", encoding="utf-8") as metadata_file:
        for record in records:
            metadata_file.write(json.dumps(record, ensure_ascii=False) + "\n")
    print(f"wrote {len(records)} mixed samples to {args.output_dir}")


def read_wav(path: Path) -> tuple[int, array]:
    with wave.open(str(path), "rb") as wav_file:
        if wav_file.getnchannels() != 1 or wav_file.getsampwidth() != 2:
            raise ValueError(f"Expected mono 16-bit WAV: {path}")
        return wav_file.getframerate(), array("h", wav_file.readframes(wav_file.getnframes()))


def write_wav(path: Path, sample_rate: int, samples: array) -> None:
    with wave.open(str(path), "wb") as wav_file:
        wav_file.setnchannels(1)
        wav_file.setsampwidth(2)
        wav_file.setframerate(sample_rate)
        wav_file.writeframes(samples.tobytes())


def mix(signal: array, noise: array, *, snr_db: float) -> array:
    if not noise:
        return array("h", signal)
    if len(noise) < len(signal):
        repeats = (len(signal) + len(noise) - 1) // len(noise)
        noise = noise * repeats
    noise = noise[: len(signal)]
    signal_rms = rms(signal)
    noise_rms = rms(noise)
    if signal_rms == 0 or noise_rms == 0:
        return array("h", signal)
    desired_noise_rms = signal_rms / (10 ** (snr_db / 20))
    gain = desired_noise_rms / noise_rms
    mixed = array("h")
    for signal_sample, noise_sample in zip(signal, noise):
        value = round(signal_sample + noise_sample * gain)
        mixed.append(max(-32768, min(32767, value)))
    return mixed


def rms(samples: array) -> float:
    if not samples:
        return 0.0
    return math.sqrt(sum(sample * sample for sample in samples) / len(samples))


def format_snr(snr: float) -> str:
    return str(int(snr)) if snr.is_integer() else str(snr).replace(".", "_")


if __name__ == "__main__":
    main()
