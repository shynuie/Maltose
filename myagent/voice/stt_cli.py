from __future__ import annotations

import argparse
import logging
from pathlib import Path

from myagent.logging import configure_logging
from myagent.voice import STTRequest, create_stt_provider


logger = logging.getLogger(__name__)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Transcribe audio using local faster-whisper.")
    parser.add_argument("--file", required=True, type=Path, help="Audio file to transcribe.")
    parser.add_argument("--model", default="small", help="Whisper model size. Default: small.")
    parser.add_argument(
        "--provider",
        choices=("faster-whisper", "fun-asr-nano", "qwen3-asr-0.6b"),
        default="qwen3-asr-0.6b",
    )
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
    configure_logging()
    args = build_parser().parse_args()
    result = create_stt_provider(
        provider=args.provider,
        model=args.model,
        device=args.device,
        compute_type=args.compute_type,
    ).transcribe(
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
            logger.info(
                "segment start=%.2fs end=%.2fs text=%s",
                segment.start,
                segment.end,
                segment.text,
            )
        return

    logger.info("transcript text=%s", result.text)
