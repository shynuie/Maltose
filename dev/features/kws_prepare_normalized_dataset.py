"""Build one normalized copy of the local KWS training sources."""

from __future__ import annotations

import argparse
import json
import wave
from pathlib import Path


def normalize_pcm(pcm: bytes, target_peak: int) -> tuple[bytes, int, float]:
    import numpy

    samples = numpy.frombuffer(pcm, dtype=numpy.int16).astype(numpy.int32)
    source_peak = int(numpy.max(numpy.abs(samples))) if len(samples) else 0
    if source_peak == 0:
        return pcm, 0, 1.0
    gain = target_peak / source_peak
    scaled = numpy.clip(samples.astype(numpy.float32) * gain, -32768, 32767)
    return scaled.astype(numpy.int16).tobytes(), source_peak, gain


def normalize_file(source: Path, target: Path, target_peak: int) -> dict[str, object]:
    with wave.open(str(source), "rb") as src:
        params = src.getparams()
        if params.sampwidth != 2:
            raise ValueError(f"expected 16-bit PCM: {source}")
        pcm = src.readframes(src.getnframes())
    normalized, source_peak, gain = normalize_pcm(pcm, target_peak)
    target.parent.mkdir(parents=True, exist_ok=True)
    with wave.open(str(target), "wb") as dst:
        dst.setparams(params)
        dst.writeframes(normalized)
    return {
        "source": str(source),
        "path": str(target),
        "source_peak": source_peak,
        "target_peak": target_peak if source_peak else 0,
        "gain": round(gain, 6),
    }


def list_sources(repo: Path) -> dict[str, list[Path]]:
    train_dir = repo / "data/kws/training/marvin-mini"
    groups: dict[str, list[Path]] = {}
    for name, manifest in {
        "positive": "positive_train.txt",
        "positive_mixed": "positive_mixed_train.txt",
        "negative": "negative_train.txt",
        "noise": "noise_train.txt",
    }.items():
        groups[name] = [Path(line.strip()).expanduser() for line in (train_dir / manifest).read_text().splitlines() if line.strip()]
    groups["tts"] = sorted((repo / "data/kws/tts/mac_say_v2").glob("*.wav"))
    groups["tts"] += sorted((repo / "data/kws/tts/edge_online").glob("*.wav"))
    return groups


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--repo", type=Path, default=Path("."))
    parser.add_argument("--target-peak", type=int, default=12000)
    parser.add_argument("--output", type=Path, default=Path("data/kws/training/marvin-mini/normalized-12000"))
    args = parser.parse_args()
    if not 1 <= args.target_peak <= 32767:
        raise ValueError("target peak must be between 1 and 32767")

    groups = list_sources(args.repo)
    metadata: list[dict[str, object]] = []
    for group, sources in groups.items():
        manifest_lines = []
        for index, source in enumerate(sources, 1):
            if not source.exists():
                raise FileNotFoundError(source)
            target = args.output / group / f"{index:04d}-{source.name}"
            item = normalize_file(source, target, args.target_peak)
            metadata.append({"group": group, **item})
            manifest_lines.append(str(target))
        (args.output / f"{group}.txt").parent.mkdir(parents=True, exist_ok=True)
        (args.output / f"{group}.txt").write_text("\n".join(manifest_lines) + "\n", encoding="utf-8")

    (args.output / "metadata.jsonl").write_text(
        "".join(json.dumps(item, ensure_ascii=False) + "\n" for item in metadata),
        encoding="utf-8",
    )
    print(f"output={args.output}")
    for group, sources in groups.items():
        print(f"{group}={len(sources)}")
    print(f"total={len(metadata)} target_peak={args.target_peak}")


if __name__ == "__main__":
    main()
