from __future__ import annotations

import argparse
import audioop
import queue
import wave
from pathlib import Path


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Record a wake-word sample until Enter.")
    parser.add_argument("--device", default="3", help="sounddevice input device id or name.")
    parser.add_argument("--output", type=Path, default=Path("recordings/kws-wake-sample.wav"))
    parser.add_argument("--sample-rate", type=int, default=16000)
    parser.add_argument("--block-ms", type=int, default=100)
    return parser


def main() -> None:
    args = build_parser().parse_args()

    import sounddevice as sd

    device = _parse_device(args.device)
    blocksize = args.sample_rate * args.block_ms // 1000
    audio_queue: queue.Queue[bytes] = queue.Queue()
    chunks: list[bytes] = []

    def callback(indata, _frames, _time, status) -> None:
        if status:
            print(f"audio_status {status}", flush=True)
        audio_queue.put(bytes(indata))

    print(
        f"recording_started path={args.output} device={device} "
        f"sample_rate={args.sample_rate}",
        flush=True,
    )
    print("Say the wake word once, then press Enter to stop.", flush=True)

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
    args.output.parent.mkdir(parents=True, exist_ok=True)
    with wave.open(str(args.output), "wb") as wav_file:
        wav_file.setnchannels(1)
        wav_file.setsampwidth(2)
        wav_file.setframerate(args.sample_rate)
        wav_file.writeframes(pcm)

    seconds = len(pcm) / (args.sample_rate * 2)
    rms = audioop.rms(pcm, 2) if pcm else 0
    peak = audioop.max(pcm, 2) if pcm else 0
    print(
        f"recording_done path={args.output} seconds={seconds:.2f} "
        f"rms={rms} peak={peak}",
        flush=True,
    )


def _parse_device(device: str) -> str | int:
    try:
        return int(device)
    except ValueError:
        return device


if __name__ == "__main__":
    main()
