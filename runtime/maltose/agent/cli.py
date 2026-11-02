from __future__ import annotations

import argparse
import logging
import shlex
from contextlib import ExitStack
from pathlib import Path

from maltose.agent.agent import VoiceAgent
from maltose.ui import MaltoseBridge
from maltose.ui.native import NativeRuntimeBridge
from maltose.ui.native_tools import NativePanelToolAdapter
from maltose.codex.native_tools import NativeCodexToolAdapter
from maltose.ui.workflow import NativeWorkflowToolAdapter
from maltose.agent.brain import EchoBrain, OpenClawBrain
from maltose.agent.config import AgentConfig, load_cli_defaults
from maltose.agent.environment import EnvironmentTools
from maltose.agent.taskbrain import (
    MemoryStore,
    LanceMemoryStore,
    OpenAICompatibleTaskModel,
    QwenEmbeddingProvider,
    TaskBrain,
    UserProfileStore,
)
from maltose.agent.tasks import AssistantMessageWorker, CodexReadOnlyWorker, TaskManager, TaskStore
from maltose.agent.capabilities import MCPStdioClient, MCPToolAdapter
from maltose.filesystem.approval import ApprovalManager, AuditLog
from maltose.filesystem.paths import FilesystemRoot, PathResolver
from maltose.filesystem.policy import PolicyEngine, WorkingRoot
from maltose.filesystem.service import FileService
from maltose.filesystem.tools import FileToolAdapter
from maltose.filesystem.ui import FilesystemApprovalUI
from maltose.agent.search import BraveSearchProvider, WebResearchWorker
from maltose.knowledge.config import KnowledgeConfig
from maltose.knowledge.chunker import DocumentChunker
from maltose.knowledge.embeddings import LazyEmbeddingProvider
from maltose.knowledge.indexer import DocumentIndexer
from maltose.knowledge.ingestion import DocumentIngestionService
from maltose.knowledge.parsers import MarkdownParser, PDFParser, ParserRegistry, TextParser
from maltose.knowledge.repositories import LanceVectorRepository, MetadataRepository
from maltose.knowledge.retrieval import DocumentKnowledgeService
from maltose.knowledge.source_reader import SourceReader
from maltose.knowledge.scanner import DocumentScanner
from maltose.knowledge.summaries import ExtractiveDocumentSummarizer
from maltose.knowledge.tools import DocumentToolAdapter
from maltose.knowledge.curation import CuratedKnowledgeStore, KnowledgeProposalStore, KnowledgeSourcePolicy
from maltose.knowledge.curation_tools import KnowledgeCurationToolAdapter
from maltose.knowledge.curation_ui import KnowledgeProposalUI
from maltose.knowledge.unified_retrieval import UnifiedKnowledgeService, UnifiedKnowledgeToolAdapter
from maltose.logging import configure_logging
from maltose.paths import default_config_path
from maltose.runtime import EventHub, PresentationStore
from maltose.runtime.ownership import ManagedWorker
from maltose.web import WebServer
from maltose.execution import (
    ArtifactPromoter,
    DockerSandboxBackend,
    ExecutionBroker,
    ExecutionPolicy,
    ExecutionToolAdapter,
    ExecutionApprovalUI,
    publish_to_event_hub,
)
from maltose.voice import (
    AudioInputDeviceController,
    NullSpeakerIdentifier,
    ProfileSpeakerIdentifier,
    SpeakerProfileStore,
    SpeakerIdentityManager,
    SpeechBrainECAPAEncoder,
    create_wake_word_detector,
    load_wake_word_config,
)
from maltose.voice.listen_cli import _parse_device
from maltose.voice.listening import VADSettings

logger = logging.getLogger(__name__)


def _parse_filesystem_root(value: str) -> tuple[str, Path]:
    name, separator, raw_path = value.partition("=")
    if not separator or not name.strip() or not raw_path.strip():
        raise argparse.ArgumentTypeError("filesystem root must use NAME=PATH")
    return name.strip(), Path(raw_path.strip())


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Run the Maltose voice assistant until Ctrl+C."
    )
    parser.add_argument(
        "--config",
        type=Path,
        default=default_config_path(),
        help="Unified TOML configuration; prefers maltose.toml, with legacy myagent.toml fallback.",
    )
    parser.add_argument("--native-stdio", action="store_true", help="Run as a native Maltose managed child.")
    parser.add_argument("--native-text-only", action="store_true", help="Disable audio for an explicitly selected text-only native session.")
    parser.add_argument("--maltose",action="store_true",help="Enable native Maltose discovery, pairing and runtime bridge.")
    parser.add_argument("--maltose-agent-id",default="agent.myagent")
    parser.add_argument("--maltose-name",default="Maltose")
    parser.add_argument("--maltose-discovery-directory",default=None)
    parser.add_argument("--maltose-state-root",default=None)
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
        "--filesystem-enabled",
        action="store_true",
        help="Enable explicitly configured filesystem capability tools.",
    )
    parser.add_argument("--filesystem-working-root", type=Path, default=Path("workspace"))
    parser.add_argument(
        "--filesystem-read-root",
        action="append",
        type=_parse_filesystem_root,
        default=[],
        metavar="NAME=PATH",
        help="Additional read-only filesystem root; may be repeated.",
    )
    parser.add_argument("--filesystem-approvals", type=Path, default=Path("data/agent/approvals.json"))
    parser.add_argument("--filesystem-trash", type=Path, default=Path("data/agent/trash"))
    parser.add_argument("--filesystem-audit", type=Path, default=Path("data/agent/filesystem_audit.jsonl"))
    parser.add_argument("--execution-enabled", action="store_true", help="Enable isolated command execution tools.")
    parser.add_argument("--execution-image", default="python:3.12-slim")
    parser.add_argument("--execution-approvals", type=Path, default=Path("data/agent/execution_approvals.json"))
    parser.add_argument("--execution-pending", type=Path, default=Path("data/agent/execution_pending.json"))
    parser.add_argument(
        "--knowledge-enabled",
        action="store_true",
        help="Enable Document Knowledge Base tools for TaskBrain.",
    )
    parser.add_argument("--knowledge-documents-root", type=Path, default=Path("documents"))
    parser.add_argument("--knowledge-queue", type=Path, default=Path("data/knowledge/indexing_queue.sqlite3"))
    parser.add_argument("--knowledge-watcher-poll-interval", type=float, default=1.0)
    parser.add_argument("--knowledge-indexing-max-attempts", type=int, default=3)
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
        "--knowledge-curation-enabled",
        action="store_true",
        help="Enable Agent knowledge proposals and Web UI review.",
    )
    parser.add_argument(
        "--knowledge-proposals",
        type=Path,
        default=Path("data/knowledge/proposals/proposals.json"),
    )
    parser.add_argument(
        "--knowledge-curated",
        type=Path,
        default=Path("data/knowledge/curated/curated.json"),
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
    parser.add_argument("--speech-mode", choices=("auto", "summary", "mute"), default="auto",
                        help="Result speech preference: voice summaries, all-input summaries, or silent.")
    parser.add_argument("--speech-target-seconds", type=float, default=15.0,
                        help="Target maximum duration of the default spoken summary (1–30 seconds).")
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


def main(*, native_owner_lost=None, native_control_ready=None) -> None:
    with ExitStack() as resources:
        _main(resources, native_owner_lost=native_owner_lost, native_control_ready=native_control_ready)


def _main(resources: ExitStack, *, native_owner_lost=None, native_control_ready=None) -> None:
    configure_logging()
    parser = build_parser()
    config_probe = argparse.ArgumentParser(add_help=False)
    config_probe.add_argument("--config", type=Path, default=default_config_path())
    config_args, _ = config_probe.parse_known_args()
    parser.set_defaults(**load_cli_defaults(config_args.config))
    args = parser.parse_args()
    if args.native_text_only and not args.native_stdio:
        parser.error("--native-text-only requires --native-stdio")
    if args.native_text_only:
        args.wake_config = None
    event_hub = EventHub()
    if args.native_stdio:
        from maltose.codex.native_service import NativeCollaborationService
        collaboration = NativeCollaborationService(config_args.config.expanduser().absolute().parent, Path(args.taskbrain_codex_cwd))
        native_bridge = NativeRuntimeBridge(event_hub, collaboration=collaboration, on_owner_lost=native_owner_lost)
    else: native_bridge = None
    runtime_session_id = native_bridge.session_id if native_bridge is not None else "cli"
    if native_bridge is not None:
        if native_control_ready is not None: native_control_ready(native_bridge.control)
        resources.callback(native_bridge.close)
        native_bridge.start()
        native_bridge.wait_for_initialize()

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
    audio_device_controller = AudioInputDeviceController(_parse_device(args.device))
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
        from maltose.voice.alibaba_kws import AlibabaKWSProcessError
        try:
            wake_word_detector = create_wake_word_detector(wake_config)
        except AlibabaKWSProcessError as error:
            parser.exit(2, f"喚醒詞服務啟動失敗：{error}\n")
        close_detector = getattr(wake_word_detector, "close", None)
        if callable(close_detector): resources.callback(close_detector)

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
        speech_mode=args.speech_mode,
        speech_target_seconds=args.speech_target_seconds,
        interruptible_tts=not args.no_interruptible_tts,
        output_dir=args.output_dir,
        wake_word_detector=wake_word_detector,
        wake_ack_text=args.wake_ack,
        wake_ack_delay=args.wake_ack_delay,
        wake_buffer_ms=args.wake_buffer_ms,
    )
    presentation = PresentationStore()
    maltose_bridge = MaltoseBridge(event_hub,agent_id=args.maltose_agent_id,name=args.maltose_name,directory=args.maltose_discovery_directory,state_root=args.maltose_state_root) if args.maltose else None
    if maltose_bridge is not None: resources.callback(maltose_bridge.close)

    def publish_ui_block(block_type: str, payload: dict[str, object]) -> None:
        block = presentation.upsert(block_type, payload)
        if args.web or args.maltose or args.native_stdio:
            event_hub.publish("ui_block", block)

    def publish_approval(block_type: str, payload: dict[str, object]) -> None:
        # Only approval managers receive this publisher. Model presentation tools
        # receive publish_ui_block and cannot forge the privileged event type.
        publish_ui_block(block_type, payload)
        if args.native_stdio and block_type == "ui_confirmation":
            event_hub.publish("native_approval", payload)

    def publish_task_progress(payload: dict[str, object]) -> None:
        publish_ui_block("ui_progress", payload)

    filesystem_approval_ui: FilesystemApprovalUI | None = None
    execution_approval_ui: ExecutionApprovalUI | None = None
    knowledge_proposal_ui: KnowledgeProposalUI | None = None
    curated_knowledge_store: CuratedKnowledgeStore | None = None
    filesystem_service: FileService | None = None
    execution_readable_roots: tuple[tuple[str, str], ...] = ()
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
        if native_bridge is not None:
            capability_adapters.append(NativePanelToolAdapter(native_bridge))
            capability_adapters.append(NativeCodexToolAdapter(native_bridge))
            if native_bridge.workflow_version == 1:
                capability_adapters.append(NativeWorkflowToolAdapter(native_bridge))
        if maltose_bridge is not None:
            capability_adapters.append(maltose_bridge)
        if args.filesystem_enabled:
            filesystem_roots = {
                "workspace": FilesystemRoot(
                    "workspace",
                    args.filesystem_working_root,
                    read=True,
                    write=True,
                    delete=True,
                ),
                **{
                    name: FilesystemRoot(name, path, read=True, write=False, delete=False)
                    for name, path in args.filesystem_read_root
                },
            }
            execution_readable_roots = tuple(
                (name, str(path)) for name, path in args.filesystem_read_root
            )
            filesystem_resolver = PathResolver(filesystem_roots)
            filesystem_approvals = ApprovalManager(args.filesystem_approvals)
            filesystem_approval_ui = FilesystemApprovalUI(
                filesystem_approvals,
                session_id=runtime_session_id,
                publisher=publish_approval,
            )
            filesystem_policy = PolicyEngine(
                filesystem_resolver,
                working_root=WorkingRoot("workspace"),
            )
            filesystem_service = FileService(
                        filesystem_resolver,
                        filesystem_policy,
                        approval_manager=filesystem_approvals,
                        audit_log=AuditLog(args.filesystem_audit),
                        session_id=runtime_session_id,
                        trash_path=args.filesystem_trash,
                        approval_notifier=filesystem_approval_ui.publish_request,
                    )
            capability_adapters.append(FileToolAdapter(filesystem_service))
            logger.info(
                "filesystem_capabilities_enabled working_root=%s",
                args.filesystem_working_root,
            )
        if args.execution_enabled:
            execution_approvals = ApprovalManager(args.execution_approvals)
            execution_approval_ui = ExecutionApprovalUI(
                execution_approvals,
                session_id=runtime_session_id,
                publisher=publish_approval,
            )
            execution_broker = ExecutionBroker(
                DockerSandboxBackend(image=args.execution_image),
                ExecutionPolicy(),
                approval_manager=execution_approvals,
                session_id=runtime_session_id,
                pending_store=args.execution_pending,
                event_publisher=publish_to_event_hub(event_hub) if (args.web or args.native_stdio) else None,
                audit_log=AuditLog(args.filesystem_audit),
                approval_notifier=execution_approval_ui.publish_request,
                artifact_promoter=(
                    ArtifactPromoter(
                        filesystem_service,
                        approval_manager=execution_approvals,
                        session_id=runtime_session_id,
                        approval_notifier=execution_approval_ui.publish_request,
                    )
                    if filesystem_service is not None else None
                ),
            )
            execution_approval_ui.execution_resumer = execution_broker.resume_promotion_by_approval
            capability_adapters.append(ExecutionToolAdapter(
                execution_broker,
                working_root=str(args.filesystem_working_root) if filesystem_service is not None else None,
                readable_roots=execution_readable_roots,
            ))
            logger.info("execution_capabilities_enabled image=%s", args.execution_image)
        if args.knowledge_curation_enabled:
            knowledge_proposals = KnowledgeProposalStore(
                args.knowledge_proposals,
                source_policy=KnowledgeSourcePolicy(
                    {"documents": args.knowledge_documents_root}
                ),
            )
            curated_knowledge = CuratedKnowledgeStore(
                args.knowledge_curated,
                embedder=embedder,
            )
            curated_knowledge_store = curated_knowledge
            knowledge_proposal_ui = KnowledgeProposalUI(
                knowledge_proposals,
                reviewer="user",
                publisher=publish_approval,
                curated_store=curated_knowledge,
            )
            capability_adapters.append(
                KnowledgeCurationToolAdapter(
                    knowledge_proposals,
                    proposal_notifier=knowledge_proposal_ui.publish_request,
                    curated_store=curated_knowledge,
                )
            )
            logger.info("knowledge_curation_enabled proposals=%s", args.knowledge_proposals)
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
                queue_path=args.knowledge_queue,
            ).resolved()
            knowledge_metadata = MetadataRepository(knowledge_config.metadata_path)
            resources.callback(knowledge_metadata.close)
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
            if curated_knowledge_store is not None:
                capability_adapters.append(
                    UnifiedKnowledgeToolAdapter(
                        UnifiedKnowledgeService(
                            truth=knowledge_service,
                            curated=curated_knowledge_store,
                        )
                    )
                )
            if knowledge_proposal_ui is not None:
                knowledge_proposal_ui.set_truth_checker(
                    lambda content: knowledge_service.search_documents(content, top_k=3)
                )
            logger.info("document_knowledge_enabled root=%s", knowledge_config.documents_root)
        task_manager = TaskManager(
            TaskStore(args.taskbrain_tasks),
            max_workers=args.taskbrain_max_workers,
            progress_publisher=publish_task_progress if (args.web or args.maltose or args.native_stdio) else None,
            control_gate=native_bridge.control if native_bridge else None,
        )
        resources.callback(task_manager.shutdown, wait=args.native_stdio)
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
            resources.callback(client.close)
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
            ui_publisher=publish_ui_block if (args.web or args.maltose or args.native_stdio) else None,
            ui_state_provider=presentation.snapshot if (args.web or args.maltose or args.native_stdio) else None,
            presentation_tools_enabled=args.web or not args.native_stdio,
            audio_device_controller=audio_device_controller,
            external_ui_context_provider=native_bridge.context if native_bridge else maltose_bridge.context if maltose_bridge else None,
            runtime_publisher=event_hub.publish,
            control_gate=native_bridge.control if native_bridge else None,
        )
    else:
        brain = EchoBrain(prefix=args.reply_prefix)
    speaker_identifier = NullSpeakerIdentifier(
        args.taskbrain_trust_user_id
    )
    speaker_store = None
    if args.speaker_recognition == "speechbrain":
        speaker_store = SpeakerProfileStore(args.speaker_profiles)
        resources.callback(speaker_store.close)
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
        audio_device_controller=audio_device_controller,
        observe_speech=args.maltose or args.native_stdio,
        voice_enabled=not args.native_text_only,
        control_gate=native_bridge.control if native_bridge else None,
    )
    if native_bridge is not None:
        native_bridge.file_service = filesystem_service
        native_bridge.attach(agent, brain)
        if native_bridge.workflow_version == 1 and callable(getattr(brain, 'process_result', None)):
            workflow = NativeWorkflowToolAdapter(native_bridge)
            brain.workflow_context_provider = workflow.snapshot
            brain.product_plan_observer = workflow.prepared_workers
        if native_bridge.presentation_version == 1:
            agent.result_handler = native_bridge.present_result
            agent.durable_result_delivery = native_bridge.result_delivery_version == 1
    if maltose_bridge is not None:
        maltose_bridge.attach(agent,brain)
    web_server: WebServer | None = None
    def handle_ui_action(action_id: str, value: object) -> None:
        if action_id == "ui.close" and isinstance(value, dict):
            block_id = value.get("block_id")
            if isinstance(block_id, str):
                presentation.close(block_id)
        if action_id in {
            "filesystem.approve",
            "filesystem.reject",
        }:
            if filesystem_approval_ui is None: raise RuntimeError("Filesystem approvals are not enabled")
            filesystem_approval_ui.handle_action(action_id, value)
        if action_id in {
            "execution.approve",
            "execution.reject",
        }:
            if execution_approval_ui is None: raise RuntimeError("Execution approvals are not enabled")
            execution_approval_ui.handle_action(action_id, value)
        if action_id in {
            "knowledge.approve",
            "knowledge.reject",
        }:
            if knowledge_proposal_ui is None: raise RuntimeError("Knowledge proposal reviews are not enabled")
            knowledge_proposal_ui.handle_action(action_id, value)
        event_hub.publish(
            "ui_action",
            {"action_id": action_id, "value": value},
        )

    if native_bridge is not None:
        native_bridge.action_handler = handle_ui_action
    if args.web:
        web_server = WebServer(
            event_hub,
            input_handler=agent.submit_text,
            action_handler=handle_ui_action,
            state_provider=lambda: {
                "state": agent.state.value,
                "turn_count": agent.turn_count,
                "presentation": presentation.snapshot(),
            },
            host=args.web_host,
            port=args.web_port,
        )
    if native_bridge is not None and args.knowledge_enabled and args.brain == "taskbrain":
        watcher = ManagedWorker("maltose.knowledge.cli", [
            "--documents-root", str(knowledge_config.documents_root),
            "--metadata", str(knowledge_config.metadata_path),
            "--vectors", str(knowledge_config.vectors_path),
            "--queue", str(knowledge_config.queue_path),
            "--device", args.knowledge_embedding_device,
            "watch", "--poll-interval", str(args.knowledge_watcher_poll_interval),
            "--max-attempts", str(args.knowledge_indexing_max_attempts),
        ], on_unexpected_exit=lambda code: event_hub.publish("runtime_worker_failed", {"name": "knowledge", "exitCode": code}))
        resources.callback(watcher.close)
    if maltose_bridge is not None:
        maltose_bridge.start()
    if web_server is not None:
        resources.callback(web_server.close)
        web_server.start()
        logger.info("web_ui_available url=http://%s:%s", *web_server.address)
    agent.run()
