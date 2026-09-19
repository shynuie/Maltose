from __future__ import annotations

import argparse
from pathlib import Path

from myagent.voice import FasterWhisperSTT, STTRequest


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Transcribe audio using local faster-whisper.")
    parser.add_argument("--file", required=True, type=Path, help="Audio file to transcribe.")
    parser.add_argument("--model", default="small", help="Whisper model size. Default: small.")
    parser.add_argument("--language", default="zh", help="Language hint. Default: zh.")
    parser.add_argument("--device", default="cpu", help="Inference device. Default: cpu.")
    parser.add_argument("--compute-type", default="int8", help="Inference compute type. Default: int8.")
    parser.add_argument("--beam-size", default=5, type=int, help="Beam size. Default: 5.")
    parser.add_argument(
        "--segments",
        action="store_true",
        help="Print timestamped segments instead of only final text.",
    )
    return parser


def main() -> None:
    args = build_parser().parse_args()
    result = FasterWhisperSTT().transcribe(
        STTRequest(
            audio_path=args.file,
            model_size=args.model,
            language=args.language,
            device=args.device,
            compute_type=args.compute_type,
            beam_size=args.beam_size,
        )
    )

    if args.segments:
        for segment in result.segments:
            print(f"[{segment.start:.2f}s -> {segment.end:.2f}s] {segment.text}")
        return

    print(result.text)
