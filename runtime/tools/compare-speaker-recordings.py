#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
from pathlib import Path

from myagent.voice.speaker import SpeechBrainECAPAEncoder


def _normalize(values: list[float]) -> list[float]:
    norm = sum(value * value for value in values) ** 0.5
    return [value / norm for value in values]


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Compare every WAV in two enrollment groups and report each file's best cross-group score."
    )
    parser.add_argument("--directory", type=Path, default=Path("recordings/enrollment"))
    parser.add_argument("--left-prefix", default="user-003", help="Filename prefix for the first group.")
    parser.add_argument("--right-prefix", default="user-002", help="Filename prefix for the second group.")
    parser.add_argument("--left-label", default="user-001")
    parser.add_argument("--right-label", default="user-002")
    parser.add_argument("--model-dir", type=Path, default=Path("models/speechbrain-ecapa"))
    parser.add_argument("--device", default="cpu")
    return parser


def main() -> None:
    args = build_parser().parse_args()
    left_paths = sorted(args.directory.glob(f"{args.left_prefix}-*.wav"))
    right_paths = sorted(args.directory.glob(f"{args.right_prefix}-*.wav"))
    if not left_paths or not right_paths:
        raise SystemExit("Both recording groups must contain at least one WAV file.")

    encoder = SpeechBrainECAPAEncoder(savedir=args.model_dir, device=args.device)
    embeddings: dict[Path, list[float]] = {}
    for path in [*left_paths, *right_paths]:
        print(f"Encoding {path}...", flush=True)
        embeddings[path] = _normalize(encoder.encode(path))

    def compare(source_paths: list[Path], target_paths: list[Path]) -> list[dict[str, object]]:
        rows = []
        for source in source_paths:
            scores = [
                (sum(left * right for left, right in zip(embeddings[source], embeddings[target])), target)
                for target in target_paths
            ]
            score, target = max(scores, key=lambda item: item[0])
            rows.append({"file": source.name, "best_match": target.name, "score": score})
        return rows

    result = {
        "left": args.left_label,
        "right": args.right_label,
        "left_to_right": compare(left_paths, right_paths),
        "right_to_left": compare(right_paths, left_paths),
        "same_prompt": [
            {
                "left_file": left.name,
                "right_file": right.name,
                "score": sum(
                    left_vector * right_vector
                    for left_vector, right_vector in zip(
                        embeddings[left], embeddings[right]
                    )
                ),
            }
            for left, right in zip(left_paths, right_paths)
        ],
    }
    print(json.dumps(result, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
