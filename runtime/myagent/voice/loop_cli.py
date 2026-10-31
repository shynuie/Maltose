from __future__ import annotations

import argparse
import logging
from datetime import datetime
from pathlib import Path

from myagent.logging import configure_logging
from myagent.voice import FasterWhisperSTT, MacOSSayTTS, STTRequest, TTSRequest
from myagent.voice.listen_cli import _parse_device
from myagent.voice.listening import VADSettings, microphone_events, write_utterance_wav


logger = logging.getLogger(__name__)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Run a local listen-transcribe-speak loop.")
    parser.add_argument("--output-dir", type=Path, default=Path("recordings"))
    parser.add_argument("--max-turns", type=int, help="Stop after this many voice turns.")
    parser.add_argument("--device", help="sounddevice input device id or name.")
    parser.add_argument("--model", default="small", help="Whisper model size.")
    parser.add_argument("--language", default="zh", help="Language hint.")
    parser.add_argument("--compute-type", default="int8", help="Whisper compute type.")
    parser.add_argument("--tts-voice", help="macOS voice name.")
    parser.add_argument("--tts-rate", type=int, help="macOS speech rate.")
    parser.add_argument("--reply-prefix", default="你說：", help="Prefix spoken before the transcript.")
    parser.add_argument("--vad-aggressiveness", type=int, default=2)
    parser.add_argument("--frame-ms", type=int, default=20)
    parser.add_argument("--start-trigger-ms", type=int, default=160)
    parser.add_argument("--end-silence-ms", type=int, default=700)
    parser.add_argument("--pre-roll-ms", type=int, default=300)
    return parser


def main() -> None:
    configure_logging()
    args = build_parser().parse_args()
    settings = VADSettings(
        frame_ms=args.frame_ms,
        aggressiveness=args.vad_aggressiveness,
        start_trigger_ms=args.start_trigger_ms,
        end_silence_ms=args.end_silence_ms,
        pre_roll_ms=args.pre_roll_ms,
    )
    transcriber = FasterWhisperSTT()
    speaker = MacOSSayTTS()
    turn_count = 0

    logger.info("voice_loop_started")
    try:
        for event in microphone_events(settings=settings, device=_parse_device(args.device)):
            if event.kind == "speech_started":
                logger.info("speech_started")
                continue

            if event.kind != "speech_ended" or event.utterance is None:
                continue

            turn_count += 1
            path = _next_output_path(args.output_dir, turn_count)
            write_utterance_wav(path, event.utterance)
            logger.info(
                "speech_ended path=%s duration=%.2fs",
                path,
                event.utterance.duration_seconds,
            )

            result = transcriber.transcribe(
                STTRequest(
                    audio_path=path,
                    model_size=args.model,
                    language=args.language,
                    compute_type=args.compute_type,
                )
            )
            logger.info("transcript text=%s", result.text)

            reply = f"{args.reply_prefix}{result.text}"
            logger.info("speaking text=%s", reply)
            speaker.synthesize(
                TTSRequest(
                    text=reply,
                    voice=args.tts_voice,
                    rate=args.tts_rate,
                )
            )
            logger.info("speaking_done")

            if args.max_turns is not None and turn_count >= args.max_turns:
                break
    except KeyboardInterrupt:
        logger.info("stopped")


def _next_output_path(output_dir: Path, turn_count: int) -> Path:
    stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    return output_dir / f"turn-{turn_count:03d}-{stamp}.wav"
