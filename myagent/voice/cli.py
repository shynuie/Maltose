from __future__ import annotations

import argparse
from pathlib import Path

from myagent.voice import MacOSSayTTS, TTSRequest


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Speak text using the local TTS provider.")
    parser.add_argument("text", help="Text to speak.")
    parser.add_argument("--voice", help="macOS voice name, for example Mei-Jia or Samantha.")
    parser.add_argument("--rate", type=int, help="Speech rate in words per minute.")
    parser.add_argument("--output", type=Path, help="Write audio to a file instead of speaking.")
    return parser


def main() -> None:
    args = build_parser().parse_args()
    request = TTSRequest(
        text=args.text,
        voice=args.voice,
        rate=args.rate,
        output_path=args.output,
    )
    MacOSSayTTS().synthesize(request)
