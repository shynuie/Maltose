from __future__ import annotations

import argparse
import json
import wave
from pathlib import Path

from maltose.voice.audio import measure_utterance
from maltose.voice.listening import Utterance


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Build a JSONL KWS training manifest.")
    parser.add_argument("--input-dir", action="append", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--split", choices=("train", "validation", "test"), required=True)
    parser.add_argument("--speaker-id", default="unknown")
    parser.add_argument("--distance", choices=("near", "normal", "far", "unknown"), default="unknown")
    parser.add_argument("--environment", default="unknown")
    return parser


def main() -> None:
    args = build_parser().parse_args()
    records = []
    seen: set[Path] = set()
    metadata_by_path: dict[Path, dict] = {}
    for root in args.input_dir:
        if not root.exists():
            raise FileNotFoundError(root)
        for metadata_path in sorted(root.rglob("metadata.jsonl")):
            with metadata_path.open(encoding="utf-8") as metadata_file:
                for line in metadata_file:
                    if not line.strip():
                        continue
                    metadata = json.loads(line)
                    metadata_path_value = Path(metadata["path"]).expanduser().resolve()
                    metadata_by_path[metadata_path_value] = metadata
        for path in sorted(root.rglob("*.wav")):
            path = path.resolve()
            if path in seen:
                continue
            seen.add(path)
            sample_rate, channels, pcm = read_wav(path)
            utterance = Utterance(pcm, sample_rate, 2, channels)
            stats = measure_utterance(utterance)
            kind = "negative" if "negative" in path.parts else "positive"
            metadata = dict(metadata_by_path.get(path, {}))
            metadata.update(
                {
                    "path": str(path),
                    "kind": metadata.get("kind", kind),
                    "keyword": metadata.get(
                        "keyword", "麥芽糖" if kind == "positive" else None
                    ),
                    "speaker_id": metadata.get("speaker_id", args.speaker_id),
                    "distance": metadata.get("distance", args.distance),
                    "environment": metadata.get("environment", args.environment),
                    "split": args.split,
                    "sample_rate": sample_rate,
                    "channels": channels,
                    "duration_seconds": stats.duration_seconds,
                    "rms": stats.rms,
                    "peak": stats.peak,
                }
            )
            records.append(metadata)
    if not records:
        raise ValueError("No WAV files found")
    args.output.parent.mkdir(parents=True, exist_ok=True)
    with args.output.open("w", encoding="utf-8") as output:
        for record in records:
            output.write(json.dumps(record, ensure_ascii=False) + "\n")
    print(f"wrote {len(records)} records to {args.output}")


def read_wav(path: Path) -> tuple[int, int, bytes]:
    with wave.open(str(path), "rb") as wav_file:
        if wav_file.getsampwidth() != 2:
            raise ValueError(f"{path} is not 16-bit PCM")
        return wav_file.getframerate(), wav_file.getnchannels(), wav_file.readframes(wav_file.getnframes())


if __name__ == "__main__":
    main()
