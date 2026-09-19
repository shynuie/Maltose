from __future__ import annotations

import argparse
import subprocess
import wave
from collections import deque
from pathlib import Path

from myagent.voice import normalize_utterance_peak
from myagent.voice.listening import Utterance, write_utterance_wav
from myagent.voice.wake import create_wake_word_detector, load_wake_word_config


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Analyze wake-command samples.")
    parser.add_argument("--wake-config", type=Path, default=Path("wake.toml"))
    parser.add_argument("--input-dir", type=Path, default=Path("recordings/wake-command-batch"))
    parser.add_argument("--pattern", default="*.wav")
    parser.add_argument("--buffer-ms", type=int, nargs="+", default=[500, 600, 700, 800, 900, 1000])
    parser.add_argument("--frame-ms", type=int, default=100)
    parser.add_argument("--model", default="small")
    parser.add_argument("--language", default="zh")
    parser.add_argument("--normalize", action="store_true")
    return parser


def main() -> None:
    args = build_parser().parse_args()
    files = [
        path
        for path in sorted(args.input_dir.glob(args.pattern))
        if "-buffer-" not in path.stem
    ]
    if not files:
        print(f"no_files input_dir={args.input_dir} pattern={args.pattern}")
        return

    for wav_path in files:
        hit_keyword, hit_time = _detect_hit(args.wake_config, wav_path, args.frame_ms)
        print(f"\nfile={wav_path} hit={hit_keyword} hit_time={hit_time}")
        if hit_keyword is None:
            continue

        for buffer_ms in args.buffer_ms:
            output = wav_path.with_name(f"{wav_path.stem}-buffer-{buffer_ms}.wav")
            extracted = _extract_with_buffer(
                args.wake_config,
                wav_path,
                output,
                frame_ms=args.frame_ms,
                wake_buffer_ms=buffer_ms,
                normalize=args.normalize,
            )
            if extracted is None:
                print(f"  buffer={buffer_ms} extract_failed")
                continue

            transcript = _transcribe(output, args.model, args.language)
            print(
                f"  buffer={buffer_ms} duration={extracted.duration_seconds:.2f}s "
                f"transcript={transcript}"
            )


def _detect_hit(
    wake_config: Path,
    wav_path: Path,
    frame_ms: int,
) -> tuple[str | None, float | None]:
    detector = create_wake_word_detector(load_wake_word_config(wake_config))
    if detector is None:
        raise ValueError("Wake word detection is disabled.")

    with wave.open(str(wav_path), "rb") as wav_file:
        sample_rate = wav_file.getframerate()
        sample_width = wav_file.getsampwidth()
        channels = wav_file.getnchannels()
        frames_per_chunk = max(1, sample_rate * frame_ms // 1000)
        elapsed = 0.0

        while True:
            pcm = wav_file.readframes(frames_per_chunk)
            if not pcm:
                return None, None

            elapsed += len(pcm) / (sample_rate * sample_width * channels)
            hit = detector.process_frame(pcm, sample_rate)
            if hit is not None:
                return hit.keyword, elapsed


def _extract_with_buffer(
    wake_config: Path,
    wav_path: Path,
    output: Path,
    frame_ms: int,
    wake_buffer_ms: int,
    normalize: bool,
) -> Utterance | None:
    detector = create_wake_word_detector(load_wake_word_config(wake_config))
    if detector is None:
        raise ValueError("Wake word detection is disabled.")

    with wave.open(str(wav_path), "rb") as wav_file:
        sample_rate = wav_file.getframerate()
        sample_width = wav_file.getsampwidth()
        channels = wav_file.getnchannels()
        frames_per_chunk = max(1, sample_rate * frame_ms // 1000)
        wake_buffer_frames = max(1, wake_buffer_ms // frame_ms)
        wake_buffer: deque[bytes] = deque(maxlen=wake_buffer_frames)
        chunks: list[bytes] = []
        hit = False

        while True:
            pcm = wav_file.readframes(frames_per_chunk)
            if not pcm:
                break

            if not hit:
                wake_buffer.append(pcm)
                detected = detector.process_frame(pcm, sample_rate)
                if detected is None:
                    continue
                hit = True
                chunks.extend(wake_buffer)
                detector.reset()
                continue

            chunks.append(pcm)

    if not hit:
        return None

    utterance = Utterance(
        pcm=b"".join(chunks),
        sample_rate=sample_rate,
        sample_width=sample_width,
        channels=channels,
    )
    if normalize:
        utterance = normalize_utterance_peak(utterance).utterance
    write_utterance_wav(output, utterance)
    return utterance


def _transcribe(wav_path: Path, model: str, language: str) -> str:
    result = subprocess.run(
        [
            "uv",
            "run",
            "myagent-stt",
            "--file",
            str(wav_path),
            "--model",
            model,
            "--language",
            language,
        ],
        check=True,
        capture_output=True,
        text=True,
    )
    output = "\n".join([result.stdout, result.stderr])
    for line in reversed(output.splitlines()):
        marker = "transcript text="
        if marker in line:
            return line.split(marker, 1)[1]
    return output.strip()


if __name__ == "__main__":
    main()
