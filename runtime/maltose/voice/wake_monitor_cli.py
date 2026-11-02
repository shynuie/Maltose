from __future__ import annotations

import argparse
import audioop
import queue
import time
from pathlib import Path

from maltose.voice.listen_cli import _parse_device
from maltose.voice.listening import list_input_devices
from maltose.voice.wake import create_wake_word_detector, load_wake_word_config


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Live wake word monitor.")
    parser.add_argument("--wake-config", type=Path, default=Path("wake.toml"))
    parser.add_argument("--device", help="sounddevice input device id or name.")
    parser.add_argument("--list-devices", action="store_true", help="List audio devices and exit.")
    parser.add_argument("--sample-rate", type=int, default=16000)
    parser.add_argument("--frame-ms", type=int, default=100)
    parser.add_argument("--duration", type=float, help="Optional duration in seconds.")
    parser.add_argument("--rms-warn", type=int, default=300)
    parser.add_argument("--peak-warn", type=int, default=3000)
    return parser


def main() -> None:
    args = build_parser().parse_args()

    if args.list_devices:
        print(list_input_devices())
        return

    import sounddevice as sd

    detector = create_wake_word_detector(load_wake_word_config(args.wake_config))
    if detector is None:
        raise ValueError("Wake word detection is disabled.")

    frame_samples = args.sample_rate * args.frame_ms // 1000
    audio_queue: queue.Queue[bytes] = queue.Queue()

    def callback(indata, _frames, _time, status) -> None:
        if status:
            print(f"\naudio_status {status}", flush=True)
        audio_queue.put(bytes(indata))

    print(
        "wake_monitor_started "
        f"device={args.device or 'default'} sample_rate={args.sample_rate} "
        f"frame_ms={args.frame_ms} duration={args.duration or 'until Ctrl-C'}",
        flush=True,
    )

    start = time.monotonic()
    frame_count = 0
    hit_count = 0

    try:
        with sd.RawInputStream(
            samplerate=args.sample_rate,
            blocksize=frame_samples,
            dtype="int16",
            channels=1,
            device=_parse_device(args.device),
            callback=callback,
        ):
            while True:
                if args.duration is not None and (time.monotonic() - start) >= args.duration:
                    break

                try:
                    pcm_frame = audio_queue.get(timeout=0.2)
                except queue.Empty:
                    continue

                frame_count += 1
                rms = audioop.rms(pcm_frame, 2)
                peak = audioop.max(pcm_frame, 2)
                hit = detector.process_frame(pcm_frame, args.sample_rate)

                level = _level_bar(rms)
                flags = []
                if rms < args.rms_warn:
                    flags.append("low_rms")
                if peak < args.peak_warn:
                    flags.append("low_peak")

                if hit is not None:
                    hit_count += 1
                    flags.append(f"HIT:{hit.keyword}")
                    detector.reset()

                elapsed = time.monotonic() - start
                flag_text = " ".join(flags)
                print(
                    f"\r{elapsed:6.1f}s frame={frame_count:05d} "
                    f"rms={rms:05d} peak={peak:05d} {level:<24} "
                    f"hits={hit_count:02d} {flag_text:<30}",
                    end="",
                    flush=True,
                )
    except KeyboardInterrupt:
        pass
    finally:
        print(f"\nwake_monitor_done hits={hit_count}", flush=True)


def _level_bar(rms: int) -> str:
    filled = min(24, rms // 250)
    return "[" + "#" * filled + "." * (24 - filled) + "]"
