from __future__ import annotations

import argparse
import logging
import shlex
from pathlib import Path

from myagent.agent.agent import VoiceAgent
from myagent.agent.brain import EchoBrain, OpenClawBrain
from myagent.agent.config import AgentConfig, load_cli_defaults
from myagent.agent.environment import EnvironmentTools
from myagent.agent.taskbrain import (
    MemoryStore,
    LanceMemoryStore,
    OpenAICompatibleTaskModel,
    QwenEmbeddingProvider,
    TaskBrain,
    UserProfileStore,
)
from myagent.agent.tasks import AssistantMessageWorker, CodexReadOnlyWorker, TaskManager, TaskStore
from myagent.agent.capabilities import MCPStdioClient, MCPToolAdapter
from myagent.agent.search import BraveSearchProvider, WebResearchWorker
from myagent.knowledge.config import KnowledgeConfig
from myagent.knowledge.chunker import DocumentChunker
from myagent.knowledge.embeddings import LazyEmbeddingProvider
from myagent.knowledge.indexer import DocumentIndexer
from myagent.knowledge.ingestion import DocumentIngestionService
from myagent.knowledge.parsers import MarkdownParser, PDFParser, ParserRegistry, TextParser
from myagent.knowledge.repositories import LanceVectorRepository, MetadataRepository
from myagent.knowledge.retrieval import DocumentKnowledgeService
from myagent.knowledge.source_reader import SourceReader
from myagent.knowledge.scanner import DocumentScanner
from myagent.knowledge.summaries import ExtractiveDocumentSummarizer
from myagent.knowledge.tools import DocumentToolAdapter
from myagent.logging import configure_logging
from myagent.runtime import EventHub
from myagent.web import WebServer
from myagent.voice import (
    NullSpeakerIdentifier,
    ProfileSpeakerIdentifier,
    SpeakerProfileStore,
    SpeakerIdentityManager,
    SpeechBrainECAPAEncoder,
    create_wake_word_detector,
    load_wake_word_config,
)
from myagent.voice.listen_cli import _parse_device
from myagent.voice.listening import VADSettings

logger = logging.getLogger(__name__)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Run the MyAgent voice assistant until Ctrl+C."
    )
    parser.add_argument(
        "--config",
        type=Path,
        default=Path("myagent.toml"),
        help="Unified TOML configuration file (default: myagent.toml if present).",
    )
    parser.add_argument("--web", action="store_true", help="Enable the local Web UI.")
    parser.add_argument("--web-host", default="127.0.0.1")
    parser.add_argument("--web-port", type=int, default=8765)
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
        "--taskbrain-mcp-command",
        action="append",
        default=[],
        help="MCP server command as one shell-like argument string; may be repeated.",
    )
    parser.add_argument("--taskbrain-mcp-timeout", type=float, default=15.0)
    parser.add_argument("--location", help="Configured user location, if known.")
    parser.add_argument(
        "--location-helper",
        help="Compiled macOS Core Location helper executable.",
    )
    parser.add_argument(
        "--external-ip-url",
        default="https://api.ipify.org?format=json",
        help="HTTPS endpoint used by get_ip_addresses.",
    )
    parser.add_argument("--environment-timeout", type=float, default=5.0)
    parser.add_argument(
        "--taskbrain-search",
        choices=("none", "brave"),
        default="speechbrain",
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
        default=Path("data/tasks/tasks.sqlite3"),
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
        default=Path("data/memory/memory.json"),
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
        default=Path("data/memory/memory.json"),
        help="Legacy JSON memory file to import into LanceDB.",
    )
    parser.add_argument("--taskbrain-user-id", default="user-001")
    parser.add_argument(
        "--speaker-recognition",
        choices=("none", "speechbrain"),
        default="speechbrain",
        help="Local speaker recognition backend.",
    )
    parser.add_argument(
        "--speaker-profiles",
        type=Path,
        default=Path("data/speaker/speaker_profiles.sqlite3"),
        help="SQLite database containing enrolled speaker profiles.",
    )
    parser.add_argument(
        "--speaker-model-dir",
        type=Path,
        default=Path("models/speechbrain-ecapa"),
        help="Local cache directory for the SpeechBrain speaker model.",
    )
    parser.add_argument(
        "--speaker-threshold",
        type=float,
        default=0.35,
        help="Cosine similarity threshold for identifying an enrolled speaker.",
    )
    parser.add_argument(
        "--taskbrain-trust-user-id",
        help="Override the fallback identity trusted for microphone turns until speaker identification is available.",
    )
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
        "--knowledge-enabled",
        action="store_true",
        help="Enable Document Knowledge Base tools for TaskBrain.",
    )
    parser.add_argument("--knowledge-documents-root", type=Path, default=Path("documents"))
    parser.add_argument(
        "--knowledge-metadata",
        type=Path,
        default=Path("data/knowledge/metadata.sqlite3"),
    )
    parser.add_argument(
        "--knowledge-vectors",
        type=Path,
        default=Path("data/knowledge/vectors.lancedb"),
    )
    parser.add_argument(
        "--knowledge-embedding",
        choices=("none", "qwen3-embedding-0.6b"),
        default="none",
        help="Embedding provider used by KDB retrieval.",
    )
    parser.add_argument(
        "--knowledge-embedding-device",
        choices=("cpu", "mps"),
        default="cpu",
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
        "--no-interruptible-tts",
        action="store_true",
        help="Keep speaking until the current say command finishes.",
    )
    parser.add_argument(
        "--wake-config",
        type=Path,
        help="TOML config file for wake word detection.",
    )
    parser.add_argument(
        "--kws-frame-ms",
        type=int,
        choices=(10, 20, 30),
        help="KWS frame size, independent from VAD frame size.",
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
    parser.add_argument(
        "--min-speech-ms",
        type=int,
        default=0,
        help="Discard VAD utterances shorter than this duration.",
    )
    return parser


def main() -> None:
    configure_logging()
    parser = build_parser()
    config_probe = argparse.ArgumentParser(add_help=False)
    config_probe.add_argument("--config", type=Path, default=Path("myagent.toml"))
    config_args, _ = config_probe.parse_known_args()
    parser.set_defaults(**load_cli_defaults(config_args.config))
    args = parser.parse_args()

    vad_settings = VADSettings(
        frame_ms=args.frame_ms,
        kws_frame_ms=args.kws_frame_ms,
        aggressiveness=args.vad_aggressiveness,
        start_trigger_ms=args.start_trigger_ms,
        end_silence_ms=args.end_silence_ms,
        pre_roll_ms=args.pre_roll_ms,
        min_speech_ms=args.min_speech_ms,
    )
    wake_word_detector = None
    if args.wake_config is not None:
        wake_config = load_wake_word_config(args.wake_config)
        sherpa_config = wake_config.sherpa_onnx
        logger.info(
            "voice_config_loaded config=%s device=%s frame_ms=%d min_speech_ms=%d stt_provider=%s "
            "kws_frame_ms=%s wake_config=%s wake_threshold=%s wake_score=%s wake_trailing_blanks=%s "
            "wake_normalization=%s",
            args.config,
            args.device,
            args.frame_ms,
            args.min_speech_ms,
            args.stt_provider,
            args.kws_frame_ms or args.frame_ms,
            args.wake_config,
            sherpa_config.keywords_threshold if sherpa_config else "n/a",
            sherpa_config.keywords_score if sherpa_config else "n/a",
            sherpa_config.num_trailing_blanks if sherpa_config else "n/a",
            wake_config.normalization_mode,
        )
        wake_word_detector = create_wake_word_detector(
            wake_config
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
        interruptible_tts=not args.no_interruptible_tts,
        output_dir=args.output_dir,
        wake_word_detector=wake_word_detector,
        wake_ack_text=args.wake_ack,
        wake_ack_delay=args.wake_ack_delay,
        wake_buffer_ms=args.wake_buffer_ms,
    )
    event_hub = EventHub()

    mcp_clients: list[MCPStdioClient] = []
    task_manager: TaskManager | None = None
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
        capability_adapters = [
            MCPToolAdapter(client, prefix=f"mcp_{index}_")
            for index, client in enumerate(mcp_clients)
        ]
        if args.knowledge_enabled:
            knowledge_embedder = embedder
            if args.knowledge_embedding == "qwen3-embedding-0.6b" and knowledge_embedder is None:
                knowledge_embedder = LazyEmbeddingProvider(
                    lambda: QwenEmbeddingProvider(device=args.knowledge_embedding_device)
                )
            if knowledge_embedder is None:
                raise RuntimeError(
                    "KDB requires an embedding provider. Set --knowledge-embedding "
                    "qwen3-embedding-0.6b or enable --taskbrain-embedding."
                )
            knowledge_config = KnowledgeConfig(
                documents_root=args.knowledge_documents_root,
                metadata_path=args.knowledge_metadata,
                vectors_path=args.knowledge_vectors,
            ).resolved()
            knowledge_metadata = MetadataRepository(knowledge_config.metadata_path)
            knowledge_parsers = ParserRegistry([TextParser(), MarkdownParser(), PDFParser()])
            knowledge_vectors = LanceVectorRepository(knowledge_config.vectors_path)
            knowledge_indexer = DocumentIndexer(
                parsers=knowledge_parsers,
                chunker=DocumentChunker(
                    chunk_size=knowledge_config.chunk_size,
                    chunk_overlap=knowledge_config.chunk_overlap,
                ),
                summarizer=ExtractiveDocumentSummarizer(),
                embedder=knowledge_embedder,
                metadata=knowledge_metadata,
                vectors=knowledge_vectors,
            )
            knowledge_service = DocumentKnowledgeService(
                metadata=knowledge_metadata,
                vectors=knowledge_vectors,
                embedder=knowledge_embedder,
                source_reader=SourceReader(
                    metadata=knowledge_metadata,
                    documents_root=knowledge_config.documents_root,
                    parsers=knowledge_parsers,
                ),
            )
            capability_adapters.append(
                DocumentToolAdapter(
                    knowledge_service,
                    ingestion=DocumentIngestionService(
                        documents_root=knowledge_config.documents_root,
                        scanner=DocumentScanner(knowledge_config.supported_extensions),
                        indexer=knowledge_indexer,
                    ),
                )
            )
            logger.info("document_knowledge_enabled root=%s", knowledge_config.documents_root)
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
        task_manager.register_worker("assistant_message", AssistantMessageWorker())
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
        for index, raw_command in enumerate(args.taskbrain_mcp_command):
            command = shlex.split(raw_command)
            client = MCPStdioClient(command, timeout=args.taskbrain_mcp_timeout)
            mcp_clients.append(client)
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
            capability_adapters=capability_adapters,
            environment_tools=EnvironmentTools(
                location=args.location,
                location_helper=args.location_helper,
                external_ip_url=args.external_ip_url,
                timeout=args.environment_timeout,
            ),
            ui_publisher=event_hub.publish if args.web else None,
        )
    else:
        brain = EchoBrain(prefix=args.reply_prefix)
    speaker_identifier = NullSpeakerIdentifier(
        args.taskbrain_trust_user_id
    )
    speaker_store = None
    if args.speaker_recognition == "speechbrain":
        speaker_store = SpeakerProfileStore(args.speaker_profiles)
        speaker_identifier = ProfileSpeakerIdentifier(
            speaker_store,
            SpeechBrainECAPAEncoder(savedir=args.speaker_model_dir),
            threshold=-1.0,
        )
        speaker_identity_manager = SpeakerIdentityManager(
            speaker_identifier,
            low_threshold=0.2,
            high_threshold=args.speaker_threshold,
        )
        logger.info("speaker_recognition_enabled backend=speechbrain threshold=%s", args.speaker_threshold)
    else:
        speaker_identity_manager = None
    agent = VoiceAgent(
        config=config,
        brain=brain,
        speaker_identifier=speaker_identifier,
        speaker_identity_manager=speaker_identity_manager,
        event_hub=event_hub,
    )
    web_server: WebServer | None = None
    if args.web:
        def handle_ui_action(action_id: str, value: object) -> None:
            event_hub.publish(
                "ui_action",
                {"action_id": action_id, "value": value},
            )

        web_server = WebServer(
            event_hub,
            input_handler=agent.submit_text,
            action_handler=handle_ui_action,
            state_provider=lambda: {
                "state": agent.state.value,
                "turn_count": agent.turn_count,
            },
            host=args.web_host,
            port=args.web_port,
        )
    try:
        if web_server is not None:
            web_server.start()
            logger.info("web_ui_available url=http://%s:%s", *web_server.address)
        agent.run()
    finally:
        if web_server is not None:
            web_server.close()
        for client in mcp_clients:
            client.close()
        if task_manager is not None:
            task_manager.shutdown(wait=False)
        if speaker_store is not None:
            speaker_store.close()
