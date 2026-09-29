from __future__ import annotations

import argparse
import json
from pathlib import Path

from .speaker import SpeakerProfileStore, SpeechBrainECAPAEncoder


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Enroll a known speaker from one or more WAV files."
    )
    parser.add_argument("--user-id", required=True, help="Stable user id for this speaker.")
    parser.add_argument(
        "--profiles",
        type=Path,
        default=Path("data/speaker/speaker_profiles.sqlite3"),
        help="SQLite speaker profile database.",
    )
    parser.add_argument(
        "--model-dir",
        type=Path,
        default=Path("models/speechbrain-ecapa"),
        help="SpeechBrain model cache directory.",
    )
    parser.add_argument("audio", nargs="+", type=Path, help="Enrollment WAV files.")
    return parser


def main() -> None:
    args = build_parser().parse_args()
    missing = [str(path) for path in args.audio if not path.is_file()]
    if missing:
        raise SystemExit(f"Audio file does not exist: {', '.join(missing)}")
    encoder = SpeechBrainECAPAEncoder(savedir=args.model_dir)
    store = SpeakerProfileStore(args.profiles)
    try:
        embeddings = [encoder.encode(path) for path in args.audio]
        result = store.enroll(
            args.user_id,
            embeddings,
            model_name=encoder.model_name,
        )
    finally:
        store.close()
    print(json.dumps(result, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
