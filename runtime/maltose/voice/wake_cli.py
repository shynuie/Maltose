from __future__ import annotations

import argparse
import logging
import queue
import time
from pathlib import Path

from maltose.logging import configure_logging
from maltose.voice.listen_cli import _parse_device
from maltose.voice.listening import list_input_devices
from maltose.voice.wake import create_wake_word_detector, load_wake_word_config


logger = logging.getLogger(__name__)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Test wake word detection only.")
    parser.add_argument("--wake-config", type=Path, default=Path("wake.toml"))
    parser.add_argument("--duration", type=float, default=30.0)
    parser.add_argument("--device", help="sounddevice input device id or name.")
    parser.add_argument("--list-devices", action="store_true", help="List audio devices and exit.")
    parser.add_argument("--sample-rate", type=int, default=16000)
    parser.add_argument("--frame-ms", type=int, default=100)
    return parser


def main() -> None:
    configure_logging()
    args = build_parser().parse_args()

    if args.list_devices:
        logger.info("audio_devices")
        for line in list_input_devices().splitlines():
            logger.info("audio_device %s", line)
        return

    import sounddevice as sd

    detector = create_wake_word_detector(load_wake_word_config(args.wake_config))
    if detector is None:
        raise ValueError("Wake word detection is disabled.")

    frame_samples = args.sample_rate * args.frame_ms // 1000
    audio_queue: queue.Queue[bytes] = queue.Queue()

    def callback(indata, _frames, _time, status) -> None:
        if status:
            logger.warning("audio_input_status %s", status)
        audio_queue.put(bytes(indata))

    logger.info(
        "wake_test_started duration=%.1fs sample_rate=%d frame_ms=%d",
        args.duration,
        args.sample_rate,
        args.frame_ms,
    )
    hit_count = 0
    start = time.monotonic()

    with sd.RawInputStream(
        samplerate=args.sample_rate,
        blocksize=frame_samples,
        dtype="int16",
        channels=1,
        device=_parse_device(args.device),
        callback=callback,
    ):
        while (time.monotonic() - start) < args.duration:
            try:
                pcm_frame = audio_queue.get(timeout=0.2)
            except queue.Empty:
                continue

            hit = detector.process_frame(pcm_frame, args.sample_rate)
            if hit is None:
                continue

            hit_count += 1
            logger.info("wake_detected keyword=%s count=%d", hit.keyword, hit_count)
            detector.reset()

    logger.info("wake_test_done hits=%d", hit_count)
