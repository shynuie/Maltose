"""Replay two wake recordings through one detector with a reset in between."""

from __future__ import annotations

import argparse
import wave
from pathlib import Path

from myagent.voice.wake import create_wake_word_detector, load_wake_word_config


def read_pcm(path: Path) -> bytes:
    with wave.open(str(path), "rb") as wav:
        if wav.getframerate() != 16000 or wav.getnchannels() != 1 or wav.getsampwidth() != 2:
            raise ValueError(f"{path}: expected mono 16 kHz 16-bit WAV")
        return wav.readframes(wav.getnframes())


def replay(detector, path: Path, frame_bytes: int) -> object | None:
    pcm = read_pcm(path)
    for offset in range(0, len(pcm) - frame_bytes + 1, frame_bytes):
        hit = detector.process_frame(pcm[offset : offset + frame_bytes], 16000)
        if hit is not None:
            return hit
    return None


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("first", type=Path)
    parser.add_argument("second", type=Path)
    parser.add_argument("--wake-config", type=Path, default=Path("wake.toml"))
    parser.add_argument("--frame-ms", type=int, default=30)
    args = parser.parse_args()

    detector = create_wake_word_detector(load_wake_word_config(args.wake_config))
    if detector is None:
        raise RuntimeError("wake detector is disabled")
    frame_bytes = 16000 * args.frame_ms // 1000 * 2
    try:
        detector.reset()
        first_hit = replay(detector, args.first, frame_bytes)
        print(f"first path={args.first} hit={first_hit}")

        health_before = getattr(detector, "health", lambda: {})()
        detector.reset()
        health_after = getattr(detector, "health", lambda: {})()
        print(f"reset health_before={health_before} health_after={health_after}")

        second_hit = replay(detector, args.second, frame_bytes)
        print(f"second path={args.second} hit={second_hit}")
        if first_hit is None or second_hit is None:
            raise SystemExit(1)
    finally:
        close = getattr(detector, "close", None)
        if callable(close):
            close()


if __name__ == "__main__":
    main()
