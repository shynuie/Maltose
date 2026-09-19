from __future__ import annotations

import argparse
import logging
from pathlib import Path

from myagent.agent.agent import VoiceAgent
from myagent.agent.brain import EchoBrain, OpenClawBrain
from myagent.agent.config import AgentConfig
from myagent.agent.taskbrain import (
    MemoryStore,
    LanceMemoryStore,
    OpenAICompatibleTaskModel,
    QwenEmbeddingProvider,
    TaskBrain,
    UserProfileStore,
)
from myagent.agent.tasks import CodexReadOnlyWorker, TaskManager, TaskStore
from myagent.agent.search import BraveSearchProvider, WebResearchWorker
from myagent.logging import configure_logging
from myagent.voice import create_wake_word_detector, load_wake_word_config
from myagent.voice.listen_cli import _parse_device
from myagent.voice.listening import VADSettings

logger = logging.getLogger(__name__)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Run the MyAgent voice assistant until Ctrl+C."
    )
    parser.add_argument(
        "--timeout",
        "-t",
        type=float,
        default=10.0,
        help="Seconds of silence in an active conversation before returning to wake standby (default: 10.0).",
    )
    parser.add_argument(
        "--continuous",
        action="store_true",
        help=argparse.SUPPRESS,
    )
    parser.add_argument(
        "--max-turns",
        type=int,
        help=argparse.SUPPRESS,
    )
    parser.add_argument(
        "--reply-prefix",
        default="收到，你說：",
        help="Prefix spoken before echoing the transcript.",
    )
    parser.add_argument(
        "--brain",
        choices=("echo", "openclaw", "taskbrain"),
        default="echo",
        help="Reasoning backend.",
    )
    parser.add_argument(
        "--openclaw-url",
        default="http://127.0.0.1:18789/v1/chat/completions",
        help="OpenClaw Gateway chat completions endpoint.",
    )
    parser.add_argument("--openclaw-token", help="OpenClaw Gateway bearer token.")
    parser.add_argument("--openclaw-model", default="openclaw/default")
    parser.add_argument("--openclaw-session", default="myagent-voice")
    parser.add_argument("--openclaw-timeout", type=float, default=120.0)
    parser.add_argument(
        "--taskbrain-url",
        default="https://api.openai.com/v1/chat/completions",
        help="OpenAI-compatible task model endpoint.",
    )
    parser.add_argument("--taskbrain-token", help="Task model bearer token, if required.")
    parser.add_argument("--taskbrain-model", default="gpt-5.6-luna")
    parser.add_argument("--taskbrain-reasoning-effort", default="none")
    parser.add_argument("--taskbrain-timeout", type=float, default=120.0)
    parser.add_argument(
        "--taskbrain-search",
        choices=("none", "brave"),
        default="none",
        help="Web search provider for TaskBrain.",
    )
    parser.add_argument(
        "--taskbrain-search-token",
        help="Brave Search API token. Defaults to BRAVE_SEARCH_API_KEY.",
    )
    parser.add_argument("--taskbrain-search-timeout", type=float, default=10.0)
    parser.add_argument(
        "--taskbrain-tasks",
        type=Path,
        default=Path("data/tasks.sqlite3"),
        help="SQLite database for durable task state.",
    )
    parser.add_argument(
        "--taskbrain-max-workers",
        type=int,
        default=2,
        help="Maximum concurrent local task workers.",
    )
    parser.add_argument(
        "--taskbrain-codex-cwd",
        type=Path,
        default=Path.cwd(),
        help="Working directory for read-only Codex tasks.",
    )
    parser.add_argument(
        "--taskbrain-codex-timeout",
        type=float,
        default=300.0,
        help="Maximum runtime for one read-only Codex task in seconds.",
    )
    parser.add_argument(
        "--taskbrain-memory",
        type=Path,
        default=Path("data/memory.json"),
        help="Persistent local memory JSON file.",
    )
    parser.add_argument(
        "--taskbrain-memory-backend",
        choices=("json", "lancedb"),
        default="json",
        help="Memory storage backend.",
    )
    parser.add_argument(
        "--taskbrain-memory-source",
        type=Path,
        default=Path("data/memory.json"),
        help="Legacy JSON memory file to import into LanceDB.",
    )
    parser.add_argument("--taskbrain-user-id", default="default")
    parser.add_argument(
        "--taskbrain-embedding",
        choices=("none", "qwen3-embedding-0.6b"),
        default="none",
        help="Memory retrieval embedding provider.",
    )
    parser.add_argument(
        "--taskbrain-embedding-device",
        choices=("cpu", "mps"),
        default="cpu",
        help="Device for the local embedding model.",
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
        default="我在",
        help="Short TTS acknowledgement after wake word detection (default: 我在).",
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

    if args.brain == "openclaw":
        brain = OpenClawBrain(
            endpoint=args.openclaw_url,
            token=args.openclaw_token,
            model=args.openclaw_model,
            session_id=args.openclaw_session,
            timeout=args.openclaw_timeout,
        )
    elif args.brain == "taskbrain":
        embedder = None
        if args.taskbrain_embedding == "qwen3-embedding-0.6b":
            embedder = QwenEmbeddingProvider(device=args.taskbrain_embedding_device)
        if args.taskbrain_memory_backend == "lancedb":
            memory = LanceMemoryStore(
                args.taskbrain_memory,
                embedder=embedder,
                user_id=args.taskbrain_user_id,
            )
            migrated = memory.migrate_json(args.taskbrain_memory_source)
            if migrated:
                logger.info("memory_json_migrated count=%d", migrated)
            profile = UserProfileStore(args.taskbrain_memory, user_id=args.taskbrain_user_id)
        else:
            memory = MemoryStore(args.taskbrain_memory, embedder=embedder)
            profile = None
        task_manager = TaskManager(
            TaskStore(args.taskbrain_tasks),
            max_workers=args.taskbrain_max_workers,
        )
        task_manager.register_worker(
            "codex_readonly",
            CodexReadOnlyWorker(
                cwd=args.taskbrain_codex_cwd,
                timeout=args.taskbrain_codex_timeout,
            ),
        )
        search_provider = None
        if args.taskbrain_search == "brave":
            search_provider = BraveSearchProvider(
                api_key=args.taskbrain_search_token,
                timeout=args.taskbrain_search_timeout,
            )
            task_manager.register_worker(
                "web_research",
                WebResearchWorker(search_provider),
            )
        brain = TaskBrain(
            model=OpenAICompatibleTaskModel(
                endpoint=args.taskbrain_url,
                token=args.taskbrain_token,
                model=args.taskbrain_model,
                timeout=args.taskbrain_timeout,
                reasoning_effort=args.taskbrain_reasoning_effort,
            ),
            memory=memory,
            profile=profile,
            task_manager=task_manager,
            search_provider=search_provider,
        )
    else:
        brain = EchoBrain(prefix=args.reply_prefix)
    agent = VoiceAgent(config=config, brain=brain)
    agent.run()
