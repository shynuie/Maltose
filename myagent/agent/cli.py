from __future__ import annotations

import argparse
import logging
from pathlib import Path

from myagent.agent.agent import VoiceAgent
from myagent.agent.brain import EchoBrain
from myagent.agent.config import AgentConfig
from myagent.logging import configure_logging
from myagent.voice.listen_cli import _parse_device
from myagent.voice.listening import VADSettings

logger = logging.getLogger(__name__)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Run the MyAgent voice assistant with standby timeout."
    )
    parser.add_argument(
        "--timeout",
        "-t",
        type=float,
        default=10.0,
        help="Standby timeout in seconds before auto-shutdown (default: 10.0).",
    )
    parser.add_argument(
        "--continuous",
        action="store_true",
        help="Return to standby after speaking until timeout occurs (default: single turn).",
    )
    parser.add_argument(
        "--max-turns",
        type=int,
        help="Max turns before shutdown in continuous mode.",
    )
    parser.add_argument(
        "--reply-prefix",
        default="收到，你說：",
        help="Prefix spoken before echoing the transcript.",
    )
    parser.add_argument(
        "--device",
        help="sounddevice input device id or name.",
    )
    parser.add_argument(
        "--output-dir",
        type=Path,
        default=Path("recordings"),
        help="Directory to save utterance audio files.",
    )
    parser.add_argument("--model", default="small", help="Whisper model size.")
    parser.add_argument("--language", default="zh", help="Whisper language hint.")
    parser.add_argument("--compute-type", default="int8", help="Whisper compute type.")
    parser.add_argument("--tts-voice", help="macOS voice name.")
    parser.add_argument("--tts-rate", type=int, help="macOS speech rate.")
    parser.add_argument("--vad-aggressiveness", type=int, default=2)
    parser.add_argument("--frame-ms", type=int, default=20)
    parser.add_argument("--start-trigger-ms", type=int, default=160)
    parser.add_argument("--end-silence-ms", type=int, default=700)
    parser.add_argument("--pre-roll-ms", type=int, default=300)
    return parser


def main() -> None:
    configure_logging()
    args = build_parser().parse_args()

    vad_settings = VADSettings(
        frame_ms=args.frame_ms,
        aggressiveness=args.vad_aggressiveness,
        start_trigger_ms=args.start_trigger_ms,
        end_silence_ms=args.end_silence_ms,
        pre_roll_ms=args.pre_roll_ms,
    )

    config = AgentConfig(
        standby_timeout=args.timeout,
        continuous=args.continuous,
        max_turns=args.max_turns,
        vad_settings=vad_settings,
        device=_parse_device(args.device),
        whisper_model=args.model,
        whisper_language=args.language,
        whisper_compute_type=args.compute_type,
        tts_voice=args.tts_voice,
        tts_rate=args.tts_rate,
        output_dir=args.output_dir,
    )

    brain = EchoBrain(prefix=args.reply_prefix)
    agent = VoiceAgent(config=config, brain=brain)
    agent.run()
