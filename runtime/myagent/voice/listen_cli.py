from __future__ import annotations

import argparse
import logging
from datetime import datetime
from pathlib import Path

from myagent.logging import configure_logging
from myagent.voice import (
    STTRequest,
    create_wake_word_detector,
    load_wake_word_config,
    normalize_utterance_peak,
    create_stt_provider,
)
from myagent.voice.listening import (
    VADSettings,
    list_input_devices,
    microphone_events,
    write_utterance_wav,
)


logger = logging.getLogger(__name__)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Listen for speech and save utterances.")
    parser.add_argument("--output-dir", type=Path, default=Path("recordings"))
    parser.add_argument("--max-utterances", type=int, help="Stop after this many utterances.")
    parser.add_argument("--device", help="sounddevice input device id or name.")
    parser.add_argument("--list-devices", action="store_true", help="List audio devices and exit.")
    parser.add_argument("--transcribe", action="store_true", help="Transcribe each utterance after saving.")
    parser.add_argument("--model", default="small", help="Whisper model size for --transcribe.")
    parser.add_argument(
        "--provider",
        choices=("faster-whisper", "fun-asr-nano", "qwen3-asr-0.6b"),
        default="qwen3-asr-0.6b",
        help="STT provider for --transcribe.",
    )
    parser.add_argument("--language", default="zh", help="Language hint for --transcribe.")
    parser.add_argument("--compute-type", default="int8", help="Whisper compute type for --transcribe.")
    parser.add_argument(
        "--stt-device",
        choices=("cpu", "mps"),
        default="cpu",
        help="STT inference device. MPS is experimental on macOS.",
    )
    parser.add_argument(
        "--no-normalize-stt-audio",
        action="store_true",
        help="Disable conservative peak normalization before --transcribe.",
    )
    parser.add_argument("--stt-target-peak", type=int, default=12000)
    parser.add_argument("--stt-min-peak", type=int, default=6000)
    parser.add_argument("--stt-max-gain", type=float, default=4.0)
    parser.add_argument(
        "--wake-config",
        type=Path,
        help="TOML config file for wake word detection.",
    )
    parser.add_argument("--vad-aggressiveness", type=int, default=2)
    parser.add_argument("--frame-ms", type=int, default=20)
    parser.add_argument("--start-trigger-ms", type=int, default=160)
    parser.add_argument("--end-silence-ms", type=int, default=700)
    parser.add_argument("--pre-roll-ms", type=int, default=300)
    return parser


def main() -> None:
    configure_logging()
    args = build_parser().parse_args()

    if args.list_devices:
        logger.info("audio_devices")
        for line in list_input_devices().splitlines():
            logger.info("audio_device %s", line)
        return

    settings = VADSettings(
        frame_ms=args.frame_ms,
        aggressiveness=args.vad_aggressiveness,
        start_trigger_ms=args.start_trigger_ms,
        end_silence_ms=args.end_silence_ms,
        pre_roll_ms=args.pre_roll_ms,
    )
    transcriber = (
        create_stt_provider(
            provider=args.provider,
            model=args.model,
            device=args.stt_device,
            compute_type=args.compute_type,
        )
        if args.transcribe
        else None
    )
    wake_word_detector = None
    if args.wake_config is not None:
        wake_word_detector = create_wake_word_detector(
            load_wake_word_config(args.wake_config)
        )
    utterance_count = 0

    logger.info("listening")
    try:
        for event in microphone_events(
            settings=settings,
            device=_parse_device(args.device),
            wake_word_detector=wake_word_detector,
        ):
            if event.kind == "wake_detected":
                logger.info("wake_detected keyword=%s", event.keyword)
                continue

            if event.kind == "wake_ack_requested":
                logger.info("wake_ack_requested")
                continue

            if event.kind == "speech_started":
                logger.info("speech_started")
                continue

            if event.kind != "speech_ended" or event.utterance is None:
                continue

            utterance_count += 1
            path = _next_output_path(args.output_dir, utterance_count)
            utterance = event.utterance
            if args.transcribe and not args.no_normalize_stt_audio:
                normalization = normalize_utterance_peak(
                    utterance,
                    target_peak=args.stt_target_peak,
                    min_peak=args.stt_min_peak,
                    max_gain=args.stt_max_gain,
                )
                logger.info(
                    "stt_audio_stats duration=%.2fs rms=%d->%d peak=%d->%d gain=%.2f normalized=%s",
                    normalization.before.duration_seconds,
                    normalization.before.rms,
                    normalization.after.rms,
                    normalization.before.peak,
                    normalization.after.peak,
                    normalization.gain,
                    normalization.gain != 1.0,
                )
                utterance = normalization.utterance

            write_utterance_wav(path, utterance)
            logger.info(
                "speech_ended path=%s duration=%.2fs",
                path,
                utterance.duration_seconds,
            )

            if transcriber is not None:
                result = transcriber.transcribe(
                    STTRequest(
                        audio_path=path,
                        model_size=args.model,
                        language=args.language,
                        compute_type=args.compute_type,
                    )
                )
                logger.info("transcript text=%s", result.text)

            if args.max_utterances is not None and utterance_count >= args.max_utterances:
                break
    except KeyboardInterrupt:
        logger.info("stopped")


def _next_output_path(output_dir: Path, utterance_count: int) -> Path:
    stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    return output_dir / f"utterance-{utterance_count:03d}-{stamp}.wav"


def _parse_device(device: str | None) -> str | int | None:
    if device is None:
        return None
    try:
        return int(device)
    except ValueError:
        return device
