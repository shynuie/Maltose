from __future__ import annotations

import argparse
import wave
from collections import deque
from pathlib import Path

from myagent.voice.listening import Utterance, write_utterance_wav
from myagent.voice.wake import create_wake_word_detector, load_wake_word_config


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Extract a wake-buffered utterance from a WAV file.")
    parser.add_argument("--wake-config", type=Path, default=Path("wake.toml"))
    parser.add_argument("--file", type=Path, default=Path("recordings/kws-command-sample.wav"))
    parser.add_argument("--output", type=Path, default=Path("recordings/kws-command-extracted.wav"))
    parser.add_argument("--frame-ms", type=int, default=100)
    parser.add_argument("--wake-buffer-ms", type=int, default=1000)
    return parser


def main() -> None:
    args = build_parser().parse_args()
    detector = create_wake_word_detector(load_wake_word_config(args.wake_config))
    if detector is None:
        raise ValueError("Wake word detection is disabled.")

    with wave.open(str(args.file), "rb") as wav_file:
        sample_rate = wav_file.getframerate()
        sample_width = wav_file.getsampwidth()
        channels = wav_file.getnchannels()
        frames_per_chunk = max(1, sample_rate * args.frame_ms // 1000)
        wake_buffer_frames = max(1, args.wake_buffer_ms // args.frame_ms)
        wake_buffer: deque[bytes] = deque(maxlen=wake_buffer_frames)
        chunks_after_wake: list[bytes] = []
        hit_keyword = None
        elapsed = 0.0
        hit_time = None

        while True:
            pcm = wav_file.readframes(frames_per_chunk)
            if not pcm:
                break

            elapsed += len(pcm) / (sample_rate * sample_width * channels)
            if hit_keyword is None:
                wake_buffer.append(pcm)
                hit = detector.process_frame(pcm, sample_rate)
                if hit is not None:
                    hit_keyword = hit.keyword
                    hit_time = elapsed
                    chunks_after_wake.extend(wake_buffer)
                    detector.reset()
                continue

            chunks_after_wake.append(pcm)

    if hit_keyword is None:
        print("wake_hit=None")
        return

    utterance = Utterance(
        pcm=b"".join(chunks_after_wake),
        sample_rate=sample_rate,
        sample_width=sample_width,
        channels=channels,
    )
    write_utterance_wav(args.output, utterance)
    print(
        f"wake_hit={hit_keyword} hit_time={hit_time:.2f}s "
        f"output={args.output} duration={utterance.duration_seconds:.2f}s"
    )


if __name__ == "__main__":
    main()
