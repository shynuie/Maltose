"""Command-line operations for the local Document Knowledge Base."""

from __future__ import annotations

import argparse
import json
import logging
import time
from pathlib import Path

from maltose.agent.taskbrain import QwenEmbeddingProvider
from maltose.knowledge.chunker import DocumentChunker
from maltose.knowledge.change_detection import DocumentChangeDetector
from maltose.knowledge.config import KnowledgeConfig
from maltose.knowledge.embeddings import EmbeddingProvider, LazyEmbeddingProvider
from maltose.knowledge.indexer import DocumentIndexer
from maltose.knowledge.parsers import MarkdownParser, PDFParser, ParserRegistry, TextParser
from maltose.knowledge.repositories import LanceVectorRepository, MetadataRepository
from maltose.knowledge.repair import find_orphan_vector_ids, find_repair_candidates
from maltose.knowledge.retrieval import DocumentKnowledgeService
from maltose.knowledge.event_dispatcher import DocumentEventDispatcher
from maltose.knowledge.queue import IndexJobStatus, SQLiteIndexingQueue
from maltose.knowledge.runtime import KnowledgeRuntime
from maltose.knowledge.scanner import DocumentScanner
from maltose.knowledge.source_reader import SourceReader
from maltose.knowledge.summaries import ExtractiveDocumentSummarizer
from maltose.knowledge.watcher import PollingDocumentWatcher
from maltose.knowledge.worker import IndexingWorker

logger = logging.getLogger(__name__)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Manage the Maltose Document Knowledge Base.")
    parser.add_argument("--documents-root", type=Path, default=Path("documents"))
    parser.add_argument("--metadata", type=Path, default=Path("data/knowledge/metadata.sqlite3"))
    parser.add_argument("--vectors", type=Path, default=Path("data/knowledge/vectors.lancedb"))
    parser.add_argument("--queue", type=Path, default=Path("data/knowledge/indexing_queue.sqlite3"))
    parser.add_argument("--device", choices=("cpu", "mps"), default="cpu")
    subparsers = parser.add_subparsers(dest="command", required=True)

    index = subparsers.add_parser("index", help="Index new and changed documents.")
    index.add_argument(
        "--force",
        action="store_true",
        help="Re-index every supported document, even when its content hash is unchanged.",
    )
    repair = subparsers.add_parser("repair", help="Repair failed or incomplete indexing jobs.")
    repair.add_argument(
        "--force",
        action="store_true",
        help="Re-index every supported document, not only failed or pending documents.",
    )
    repair.add_argument(
        "--prune-orphans",
        action="store_true",
        help="Delete vectors without active metadata; otherwise only report them.",
    )
    subparsers.add_parser("list", help="List indexed document metadata.")
    queue = subparsers.add_parser("queue", help="Inspect durable indexing jobs.")
    queue.add_argument(
        "--status",
        choices=tuple(status.value for status in IndexJobStatus),
        help="Filter jobs by status.",
    )
    search = subparsers.add_parser("search", help="Search indexed documents.")
    search.add_argument("query")
    search.add_argument("--top-k", type=int, default=5)
    watch = subparsers.add_parser("watch", help="Watch the document root and index changes.")
    watch.add_argument(
        "--poll-interval",
        type=float,
        default=1.0,
        help="Seconds between filesystem scans (default: 1.0).",
    )
    watch.add_argument(
        "--max-attempts",
        type=int,
        default=3,
        help="Maximum indexing attempts for one changed document (default: 3).",
    )
    return parser


def _build_services(args: argparse.Namespace, *, lazy_embedding: bool = False):
    config = KnowledgeConfig(
        documents_root=args.documents_root,
        metadata_path=args.metadata,
        vectors_path=args.vectors,
        queue_path=args.queue,
    ).resolved()
    parsers = ParserRegistry([TextParser(), MarkdownParser(), PDFParser()])
    scanner = DocumentScanner(config.supported_extensions)
    metadata = MetadataRepository(config.metadata_path)
    vectors = LanceVectorRepository(config.vectors_path)
    if lazy_embedding:
        embedder: EmbeddingProvider = LazyEmbeddingProvider(
            lambda: QwenEmbeddingProvider(device=args.device)
        )
    else:
        embedder = QwenEmbeddingProvider(device=args.device)
    indexer = DocumentIndexer(
        parsers=parsers,
        chunker=DocumentChunker(chunk_size=config.chunk_size, chunk_overlap=config.chunk_overlap),
        summarizer=ExtractiveDocumentSummarizer(),
        embedder=embedder,
        metadata=metadata,
        vectors=vectors,
    )
    service = DocumentKnowledgeService(
        metadata=metadata,
        vectors=vectors,
        embedder=embedder,
        source_reader=SourceReader(
            metadata=metadata,
            documents_root=config.documents_root,
            parsers=parsers,
        ),
    )
    return config, scanner, metadata, vectors, indexer, service


def main() -> None:
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s %(message)s",
    )
    args = build_parser().parse_args()
    if args.command == "list":
        config = KnowledgeConfig(
            documents_root=args.documents_root,
            metadata_path=args.metadata,
            vectors_path=args.vectors,
        ).resolved()
        with MetadataRepository(config.metadata_path) as metadata:
            print(json.dumps(metadata.list_documents(), ensure_ascii=False, indent=2))
        return

    if args.command == "queue":
        config = KnowledgeConfig(
            documents_root=args.documents_root,
            metadata_path=args.metadata,
            vectors_path=args.vectors,
            queue_path=args.queue,
        ).resolved()
        status = IndexJobStatus(args.status) if args.status else None
        queue = SQLiteIndexingQueue(config.queue_path)
        try:
            jobs = queue.list_jobs(status=status)
            print(json.dumps([_job_to_dict(job) for job in jobs], ensure_ascii=False, indent=2))
        finally:
            queue.close()
        return

    # Avoid loading the embedding model when an incremental index has no work.
    # This is especially important for moved or unchanged files.
    if args.command == "index" and not args.force:
        config = KnowledgeConfig(
            documents_root=args.documents_root,
            metadata_path=args.metadata,
            vectors_path=args.vectors,
        ).resolved()
        config.documents_root.mkdir(parents=True, exist_ok=True)
        scanner = DocumentScanner(config.supported_extensions)
        with MetadataRepository(config.metadata_path) as metadata:
            plan = DocumentChangeDetector().plan(scanner.scan(config.documents_root), metadata)
        if not plan.new_files and not plan.changed_files:
            logger.info("kdb_cli_index_no_work embedding_model=not_loaded")
            print(json.dumps({
                "indexed": 0,
                "unchanged": len(plan.unchanged_files),
                "moved": len(plan.moved_document_ids),
                "deleted": len(plan.deleted_document_ids),
                "documents": [],
            }, ensure_ascii=False, indent=2))
            return

    if args.command == "repair":
        config = KnowledgeConfig(
            documents_root=args.documents_root,
            metadata_path=args.metadata,
            vectors_path=args.vectors,
        ).resolved()
        config.documents_root.mkdir(parents=True, exist_ok=True)
        scanner = DocumentScanner(config.supported_extensions)
        with MetadataRepository(config.metadata_path) as metadata:
            scan = scanner.scan(config.documents_root)
            candidates = find_repair_candidates(scan, metadata, force=args.force)
            # The vector repository is intentionally opened only for the
            # repair preflight; no embedding model is needed to inspect it.
            vectors = LanceVectorRepository(config.vectors_path)
            orphan_ids = find_orphan_vector_ids(metadata, vectors)
        if not candidates and not orphan_ids:
            logger.info("kdb_cli_repair_no_work embedding_model=not_loaded")
            print(json.dumps({"repaired": 0, "orphan_vectors": [], "documents": []}, ensure_ascii=False, indent=2))
            return

    config, scanner, metadata, vectors, indexer, service = _build_services(
        args,
        lazy_embedding=args.command in {"watch", "repair"},
    )
    try:
        if args.command == "index":
            config.documents_root.mkdir(parents=True, exist_ok=True)
            logger.info("kdb_cli_index_started root=%s", config.documents_root)
            scan = scanner.scan(config.documents_root)
            plan = DocumentChangeDetector().plan(scan, metadata)
            candidates = scan.files if args.force else (*plan.new_files, *plan.changed_files)
            if args.force:
                logger.info("kdb_cli_index_force enabled candidates=%d", len(candidates))
            logger.info("kdb_cli_index_candidates count=%d", len(candidates))
            results = []
            for index, item in enumerate(candidates, start=1):
                logger.info("kdb_cli_index_progress current=%d total=%d path=%s", index, len(candidates), item.path)
                results.append(indexer.index(item))
            logger.info("kdb_cli_index_completed indexed=%d", len(results))
            print(json.dumps({
                "indexed": len(results),
                "unchanged": 0 if args.force else len(plan.unchanged_files),
                "moved": len(plan.moved_document_ids),
                "deleted": len(plan.deleted_document_ids),
                "documents": [result.__dict__ for result in results],
            }, ensure_ascii=False, indent=2))
        elif args.command == "repair":
            scan = scanner.scan(config.documents_root)
            candidates = find_repair_candidates(scan, metadata, force=args.force)
            logger.info("kdb_cli_repair_candidates count=%d", len(candidates))
            results = []
            for index, item in enumerate(candidates, start=1):
                logger.info(
                    "kdb_cli_repair_progress current=%d total=%d path=%s",
                    index,
                    len(candidates),
                    item.path,
                )
                results.append(indexer.index(item))
            orphan_ids = find_orphan_vector_ids(metadata, vectors)
            if orphan_ids:
                logger.warning("kdb_cli_repair_orphans count=%d ids=%s", len(orphan_ids), orphan_ids)
            if args.prune_orphans:
                for document_id in orphan_ids:
                    vectors.delete_document(document_id)
                logger.info("kdb_cli_repair_orphans_pruned count=%d", len(orphan_ids))
            print(json.dumps({
                "repaired": len(results),
                "orphan_vectors": list(orphan_ids),
                "pruned_orphans": len(orphan_ids) if args.prune_orphans else 0,
                "documents": [result.__dict__ for result in results],
            }, ensure_ascii=False, indent=2))
        elif args.command == "search":
            print(json.dumps([
                result.__dict__ for result in service.search_documents(args.query, args.top_k)
            ], ensure_ascii=False, indent=2))
        elif args.command == "watch":
            if args.poll_interval <= 0:
                raise ValueError("--poll-interval must be positive")
            if args.max_attempts < 1:
                raise ValueError("--max-attempts must be at least 1")
            config.documents_root.mkdir(parents=True, exist_ok=True)
            queue = SQLiteIndexingQueue(config.queue_path)
            runtime = KnowledgeRuntime(
                watcher=PollingDocumentWatcher(
                    config.documents_root,
                    scanner,
                ),
                dispatcher=DocumentEventDispatcher(
                    metadata=metadata,
                    queue=queue,
                    vectors=vectors,
                    max_attempts=args.max_attempts,
                ),
                queue=queue,
                worker=IndexingWorker(queue, indexer),
                poll_interval=args.poll_interval,
            )
            logger.info(
                "kdb_cli_watch_started root=%s poll_interval=%s max_attempts=%d",
                config.documents_root,
                args.poll_interval,
                args.max_attempts,
            )
            runtime.start()
            try:
                while True:
                    time.sleep(60)
            except KeyboardInterrupt:
                logger.info("kdb_cli_watch_interrupted")
            finally:
                runtime.stop()
                queue.close()
    finally:
        metadata.close()


def _job_to_dict(job) -> dict:
    return {
        "job_id": job.job_id,
        "path": str(job.scanned_file.path),
        "status": job.status.value,
        "attempts": job.attempts,
        "max_attempts": job.max_attempts,
        "last_error": job.last_error,
        "error_history": job.error_history,
        "result": job.result.__dict__ if job.result else None,
    }


if __name__ == "__main__":
    main()
