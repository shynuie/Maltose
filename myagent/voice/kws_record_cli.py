from __future__ import annotations

import argparse
import audioop
import logging
import queue
import time
import wave
from datetime import datetime
from pathlib import Path

from myagent.logging import configure_logging
from myagent.voice.listen_cli import _parse_device
from myagent.voice.listening import list_input_devices


logger = logging.getLogger(__name__)

NEGATIVE_PROMPTS = (
    "請說：你好，今天過得怎麼樣？",
    "請說：幫我查一下今天的天氣。",
    "請說：我想聽一段音樂。",
    "請說：現在幾點了？",
    "請說：這是一段和喚醒詞無關的普通句子。",
    "按下 Enter 後請保持靜音。",
)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Record fixed-length wake-word samples for KWS evaluation."
    )
    parser.add_argument(
        "--kind",
        choices=("positive", "negative"),
        default="positive",
        help="Sample kind; negative mode displays speech/silence prompts.",
    )
    parser.add_argument(
        "--prompt",
        action="append",
        dest="prompts",
        help="Prompt for negative mode; can be repeated. Overrides default prompts.",
    )
    parser.add_argument(
        "--output-dir",
        type=Path,
        default=None,
        help="Directory for recorded WAV files. Defaults by --kind.",
    )
    parser.add_argument(
        "--count",
        type=int,
        help="Stop after this many recordings; otherwise continue until Ctrl-C.",
    )
    parser.add_argument(
        "--duration",
        type=float,
        default=2.0,
        help="Seconds to record after pressing Enter (default: 2.0).",
    )
    parser.add_argument("--device", help="sounddevice input device id or name.")
    parser.add_argument("--list-devices", action="store_true")
    parser.add_argument("--sample-rate", type=int, default=16000)
    parser.add_argument(
        "--frame-ms",
        type=int,
        default=20,
        help="Audio callback block size in milliseconds (default: 20).",
    )
    return parser


def main() -> None:
    configure_logging()
    args = build_parser().parse_args()

    if args.list_devices:
        for line in list_input_devices().splitlines():
            logger.info("audio_device %s", line)
        return

    if args.count is not None and args.count <= 0:
        raise ValueError("--count must be greater than zero")
    if args.duration <= 0:
        raise ValueError("--duration must be greater than zero")
    if args.sample_rate <= 0 or args.frame_ms <= 0:
        raise ValueError("--sample-rate and --frame-ms must be greater than zero")

    output_dir = args.output_dir or Path("recordings/kws") / args.kind
    output_dir.mkdir(parents=True, exist_ok=True)
    frame_samples = args.sample_rate * args.frame_ms // 1000
    if frame_samples <= 0:
        raise ValueError("--frame-ms is too small for the selected sample rate")

    import sounddevice as sd

    logger.info(
        "kws_record_ready output_dir=%s duration=%.2fs sample_rate=%d frame_ms=%d device=%s",
        output_dir,
        args.duration,
        args.sample_rate,
        args.frame_ms,
        args.device or "default",
    )
    prompts = tuple(args.prompts or NEGATIVE_PROMPTS) if args.kind == "negative" else ()
    if args.kind == "positive":
        logger.info("按 Enter 開始錄音；錄音時請說：麥芽糖。Ctrl-C 結束。")
    else:
        logger.info("負樣本錄音開始；每次會先提示要說的內容。Ctrl-C 結束。")

    recorded = 0
    try:
        while args.count is None or recorded < args.count:
            if args.kind == "negative":
                prompt = prompts[recorded % len(prompts)]
                print(
                    f"[{recorded + 1}] {prompt}\n按 Enter 開始錄音：",
                    end="",
                    flush=True,
                )
            input()
            recorded += 1
            pcm = record_audio(
                sd,
                device=_parse_device(args.device),
                sample_rate=args.sample_rate,
                frame_samples=frame_samples,
                duration=args.duration,
            )
            path = next_recording_path(output_dir, recorded, kind=args.kind)
            write_pcm_wav(path, pcm, sample_rate=args.sample_rate)
            rms = audioop.rms(pcm, 2)
            peak = audioop.max(pcm, 2)
            logger.info(
                "kws_record_saved index=%d path=%s duration=%.2fs rms=%d peak=%d",
                recorded,
                path,
                len(pcm) / (args.sample_rate * 2),
                rms,
                peak,
            )
            if args.count is None or recorded < args.count:
                if args.kind == "positive":
                    logger.info("按 Enter 錄製下一次。")
    except (KeyboardInterrupt, EOFError):
        logger.info("kws_record_stopped recordings=%d", recorded)


def record_audio(
    sounddevice,
    *,
    device: str | int | None,
    sample_rate: int,
    frame_samples: int,
    duration: float,
) -> bytes:
    audio_queue: queue.Queue[bytes] = queue.Queue()

    def callback(indata, _frames, _time, status) -> None:
        if status:
            logger.warning("audio_input_status %s", status)
        audio_queue.put(bytes(indata))

    frames: list[bytes] = []
    deadline = time.monotonic() + duration
    with sounddevice.RawInputStream(
        samplerate=sample_rate,
        blocksize=frame_samples,
        dtype="int16",
        channels=1,
        device=device,
        callback=callback,
    ):
        while time.monotonic() < deadline:
            remaining = max(0.01, deadline - time.monotonic())
            try:
                frames.append(audio_queue.get(timeout=remaining))
            except queue.Empty:
                break
    return b"".join(frames)


def next_recording_path(output_dir: Path, index: int, *, kind: str = "positive") -> Path:
    stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    return output_dir / f"kws-{kind}-{index:03d}-{stamp}.wav"


def write_pcm_wav(path: Path, pcm: bytes, *, sample_rate: int) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with wave.open(str(path), "wb") as wav_file:
        wav_file.setnchannels(1)
        wav_file.setsampwidth(2)
        wav_file.setframerate(sample_rate)
        wav_file.writeframes(pcm)


if __name__ == "__main__":
    main()
