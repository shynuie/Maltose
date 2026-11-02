"""Benchmark wake recall before and after a detector reset."""

from __future__ import annotations

import argparse
import wave
from pathlib import Path

from myagent.voice.wake import create_wake_word_detector, load_wake_word_config


def read_pcm(path: Path) -> bytes:
    with wave.open(str(path), "rb") as wav:
        if (wav.getframerate(), wav.getnchannels(), wav.getsampwidth()) != (16000, 1, 2):
            raise ValueError(f"unsupported WAV format: {path}")
        return wav.readframes(wav.getnframes())


def replay(detector, pcm: bytes, frame_bytes: int) -> object | None:
    for offset in range(0, len(pcm) - frame_bytes + 1, frame_bytes):
        hit = detector.process_frame(pcm[offset : offset + frame_bytes], 16000)
        if hit is not None:
            return hit
    return None


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("input_dir", type=Path)
    parser.add_argument("--wake-config", type=Path, default=Path("wake.toml"))
    parser.add_argument("--frame-ms", type=int, default=30)
    args = parser.parse_args()

    paths = sorted(args.input_dir.rglob("*.wav"))
    detector = create_wake_word_detector(load_wake_word_config(args.wake_config))
    if detector is None:
        raise RuntimeError("wake detector is disabled")
    frame_bytes = 16000 * args.frame_ms // 1000 * 2
    first_hits = second_hits = both_hits = first_only = second_only = 0
    state_failures = 0
    try:
        for path in paths:
            pcm = read_pcm(path)
            detector.reset()
            first = replay(detector, pcm, frame_bytes) is not None
            detector.reset()
            health = getattr(detector, "health", lambda: {})()
            if health.get("kws_state") not in (None, 0) or health.get("buffered_bytes") not in (None, 0):
                state_failures += 1
            second = replay(detector, pcm, frame_bytes) is not None
            first_hits += first
            second_hits += second
            both_hits += first and second
            first_only += first and not second
            second_only += second and not first
            print(f"{path}: first={first} second={second} health={health}")
    finally:
        close = getattr(detector, "close", None)
        if callable(close):
            close()

    total = len(paths)
    print("summary")
    print(f"total={total}")
    print(f"first_hits={first_hits}/{total}")
    print(f"second_hits={second_hits}/{total}")
    print(f"both_hits={both_hits}/{total}")
    print(f"first_only={first_only}")
    print(f"second_only={second_only}")
    print(f"reset_state_failures={state_failures}")


if __name__ == "__main__":
    main()
