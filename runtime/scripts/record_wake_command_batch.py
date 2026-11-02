from __future__ import annotations

import argparse
import audioop
import queue
import wave
from pathlib import Path


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Record multiple wake-command samples.")
    parser.add_argument("--device", default="3", help="sounddevice input device id or name.")
    parser.add_argument("--count", type=int, default=5)
    parser.add_argument("--output-dir", type=Path, default=Path("recordings/wake-command-batch"))
    parser.add_argument("--prefix", default="sample")
    parser.add_argument(
        "--prompt",
        default="Say: 麥芽糖 + command. Press Enter to stop this sample.",
        help="Prompt printed before each recording.",
    )
    parser.add_argument("--sample-rate", type=int, default=16000)
    parser.add_argument("--block-ms", type=int, default=100)
    return parser


def main() -> None:
    args = build_parser().parse_args()

    import sounddevice as sd

    device = _parse_device(args.device)
    blocksize = args.sample_rate * args.block_ms // 1000
    args.output_dir.mkdir(parents=True, exist_ok=True)

    for index in range(1, args.count + 1):
        audio_queue: queue.Queue[bytes] = queue.Queue()
        chunks: list[bytes] = []
        output = args.output_dir / f"{args.prefix}-{index:02d}.wav"

        def callback(indata, _frames, _time, status) -> None:
            if status:
                print(f"audio_status {status}", flush=True)
            audio_queue.put(bytes(indata))

        print(
            f"\n[{index}/{args.count}] recording_started path={output} device={device}",
            flush=True,
        )
        print(args.prompt, flush=True)

        with sd.RawInputStream(
            samplerate=args.sample_rate,
            blocksize=blocksize,
            dtype="int16",
            channels=1,
            device=device,
            callback=callback,
        ):
            input()
            while not audio_queue.empty():
                chunks.append(audio_queue.get_nowait())

        pcm = b"".join(chunks)
        with wave.open(str(output), "wb") as wav_file:
            wav_file.setnchannels(1)
            wav_file.setsampwidth(2)
            wav_file.setframerate(args.sample_rate)
            wav_file.writeframes(pcm)

        seconds = len(pcm) / (args.sample_rate * 2)
        rms = audioop.rms(pcm, 2) if pcm else 0
        peak = audioop.max(pcm, 2) if pcm else 0
        print(
            f"recording_done path={output} seconds={seconds:.2f} rms={rms} peak={peak}",
            flush=True,
        )


def _parse_device(device: str) -> str | int:
    try:
        return int(device)
    except ValueError:
        return device


if __name__ == "__main__":
    main()
