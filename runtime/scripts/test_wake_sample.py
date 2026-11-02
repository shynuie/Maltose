from __future__ import annotations

import argparse
import wave
from pathlib import Path

from maltose.voice.wake import create_wake_word_detector, load_wake_word_config


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Run KWS against a recorded WAV file.")
    parser.add_argument("--wake-config", type=Path, default=Path("wake.toml"))
    parser.add_argument("--file", type=Path, default=Path("recordings/kws-wake-sample.wav"))
    parser.add_argument("--frame-ms", type=int, default=100)
    return parser


def main() -> None:
    args = build_parser().parse_args()
    detector = create_wake_word_detector(load_wake_word_config(args.wake_config))
    if detector is None:
        raise ValueError("Wake word detection is disabled.")

    hits: list[str] = []
    with wave.open(str(args.file), "rb") as wav_file:
        sample_rate = wav_file.getframerate()
        frames_per_chunk = max(1, sample_rate * args.frame_ms // 1000)

        while True:
            pcm = wav_file.readframes(frames_per_chunk)
            if not pcm:
                break

            hit = detector.process_frame(pcm, sample_rate)
            if hit is not None:
                hits.append(hit.keyword)
                detector.reset()

    print(f"hits={hits}")


if __name__ == "__main__":
    main()
