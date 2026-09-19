from __future__ import annotations

import argparse
import logging
from pathlib import Path

from myagent.agent.agent import VoiceAgent
from myagent.agent.brain import EchoBrain
from myagent.agent.config import AgentConfig
from myagent.logging import configure_logging
from myagent.voice import create_wake_word_detector, load_wake_word_config
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
    parser.add_argument(
        "--stt-provider",
        choices=("faster-whisper", "fun-asr-nano", "qwen3-asr-0.6b"),
        default="qwen3-asr-0.6b",
        help="Speech-to-text provider.",
    )
    parser.add_argument("--language", default="zh", help="Whisper language hint.")
    parser.add_argument("--compute-type", default="int8", help="Whisper compute type.")
    parser.add_argument(
        "--stt-device",
        choices=("cpu", "mps"),
        default="cpu",
        help="STT inference device. MPS is experimental on macOS.",
    )
    parser.add_argument(
        "--no-normalize-stt-audio",
        action="store_true",
        help="Disable conservative peak normalization before Whisper STT.",
    )
    parser.add_argument("--stt-target-peak", type=int, default=12000)
    parser.add_argument("--stt-min-peak", type=int, default=6000)
    parser.add_argument("--stt-max-gain", type=float, default=4.0)
    parser.add_argument("--tts-voice", help="macOS voice name.")
    parser.add_argument("--tts-rate", type=int, help="macOS speech rate.")
    parser.add_argument(
        "--wake-config",
        type=Path,
        help="TOML config file for wake word detection.",
    )
    parser.add_argument(
        "--wake-ack",
        help="Optional short TTS acknowledgement after wake word detection.",
    )
    parser.add_argument(
        "--wake-ack-delay",
        type=float,
        default=0.8,
        help="Seconds to wait for follow-up speech before speaking --wake-ack.",
    )
    parser.add_argument(
        "--wake-buffer-ms",
        type=int,
        default=1000,
        help="Audio kept before wake detection for one-shot commands.",
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

    vad_settings = VADSettings(
        frame_ms=args.frame_ms,
        aggressiveness=args.vad_aggressiveness,
        start_trigger_ms=args.start_trigger_ms,
        end_silence_ms=args.end_silence_ms,
        pre_roll_ms=args.pre_roll_ms,
    )
    wake_word_detector = None
    if args.wake_config is not None:
        wake_word_detector = create_wake_word_detector(
            load_wake_word_config(args.wake_config)
        )

    config = AgentConfig(
        standby_timeout=args.timeout,
        continuous=args.continuous,
        max_turns=args.max_turns,
        vad_settings=vad_settings,
        device=_parse_device(args.device),
        whisper_model=args.model,
        stt_provider=args.stt_provider,
        whisper_language=args.language,
        whisper_compute_type=args.compute_type,
        stt_device=args.stt_device,
        normalize_stt_audio=not args.no_normalize_stt_audio,
        stt_target_peak=args.stt_target_peak,
        stt_min_peak=args.stt_min_peak,
        stt_max_gain=args.stt_max_gain,
        tts_voice=args.tts_voice,
        tts_rate=args.tts_rate,
        output_dir=args.output_dir,
        wake_word_detector=wake_word_detector,
        wake_ack_text=args.wake_ack,
        wake_ack_delay=args.wake_ack_delay,
        wake_buffer_ms=args.wake_buffer_ms,
    )

    brain = EchoBrain(prefix=args.reply_prefix)
    agent = VoiceAgent(config=config, brain=brain)
    agent.run()
