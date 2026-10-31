from __future__ import annotations

import argparse
import logging
from pathlib import Path

from maltose.logging import configure_logging
from maltose.voice.kws_replay_cli import read_wav
from maltose.voice.listening import UtteranceSegmenter, VADSettings, WebRTCVoiceActivityDetector


logger = logging.getLogger(__name__)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Replay WAV files through WebRTC VAD.")
    parser.add_argument("--input-dir", type=Path, required=True)
    parser.add_argument("--pattern", default="*.wav")
    parser.add_argument("--sample-rate", type=int, default=16000)
    parser.add_argument("--frame-ms", type=int, default=20)
    parser.add_argument("--aggressiveness", type=int, default=2)
    parser.add_argument("--start-trigger-ms", type=int, default=160)
    parser.add_argument("--end-silence-ms", type=int, default=700)
    parser.add_argument("--pre-roll-ms", type=int, default=300)
    parser.add_argument("--min-speech-ms", type=int, default=300)
    return parser


def main() -> None:
    configure_logging()
    args = build_parser().parse_args()
    paths = sorted(args.input_dir.glob(args.pattern))
    if not paths:
        raise FileNotFoundError(f"No WAV files found under {args.input_dir!s}")

    settings = VADSettings(
        sample_rate=args.sample_rate,
        frame_ms=args.frame_ms,
        aggressiveness=args.aggressiveness,
        start_trigger_ms=args.start_trigger_ms,
        end_silence_ms=args.end_silence_ms,
        pre_roll_ms=args.pre_roll_ms,
        min_speech_ms=args.min_speech_ms,
    )
    logger.info(
        "vad_replay_started files=%d frame_ms=%d aggressiveness=%d "
        "start_trigger_ms=%d end_silence_ms=%d min_speech_ms=%d",
        len(paths),
        settings.frame_ms,
        settings.aggressiveness,
        settings.start_trigger_ms,
        settings.end_silence_ms,
        settings.min_speech_ms,
    )

    speech_started = 0
    speech_ended = 0
    for path in paths:
        sample_rate, pcm = read_wav(path)
        if sample_rate != settings.sample_rate:
            raise ValueError(f"{path} has sample rate {sample_rate}, expected {settings.sample_rate}")
        detector = WebRTCVoiceActivityDetector(settings.aggressiveness)
        segmenter = UtteranceSegmenter(detector, settings)
        events = []
        frame_bytes = settings.frame_byte_count
        padded_pcm = pcm + b"\0" * frame_bytes * settings.end_silence_frames
        for offset in range(0, len(padded_pcm) - frame_bytes + 1, frame_bytes):
            events.extend(segmenter.process_frame(padded_pcm[offset : offset + frame_bytes]))
        started = sum(event.kind == "speech_started" for event in events)
        ended = sum(event.kind == "speech_ended" for event in events)
        speech_started += started
        speech_ended += ended
        logger.info(
            "vad_replay_file path=%s speech_started=%d speech_ended=%d utterance_ms=%s",
            path,
            started,
            ended,
            ",".join(str(round(event.utterance.duration_seconds * 1000)) for event in events if event.utterance),
        )

    logger.info(
        "vad_replay_summary total=%d speech_started=%d speech_ended=%d "
        "accepted_rate=%.4f",
        len(paths),
        speech_started,
        speech_ended,
        speech_ended / len(paths),
    )


if __name__ == "__main__":
    main()
