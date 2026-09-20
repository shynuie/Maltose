"""Command-line operations for the local Document Knowledge Base."""

from __future__ import annotations

import argparse
import json
import logging
from pathlib import Path

from myagent.agent.taskbrain import QwenEmbeddingProvider
from myagent.knowledge.chunker import DocumentChunker
from myagent.knowledge.change_detection import DocumentChangeDetector
from myagent.knowledge.config import KnowledgeConfig
from myagent.knowledge.embeddings import EmbeddingProvider
from myagent.knowledge.indexer import DocumentIndexer
from myagent.knowledge.parsers import MarkdownParser, PDFParser, ParserRegistry, TextParser
from myagent.knowledge.repositories import LanceVectorRepository, MetadataRepository
from myagent.knowledge.retrieval import DocumentKnowledgeService
from myagent.knowledge.scanner import DocumentScanner
from myagent.knowledge.source_reader import SourceReader
from myagent.knowledge.summaries import ExtractiveDocumentSummarizer

logger = logging.getLogger(__name__)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Manage the MyAgent Document Knowledge Base.")
    parser.add_argument("--documents-root", type=Path, default=Path("documents"))
    parser.add_argument("--metadata", type=Path, default=Path("data/knowledge/metadata.sqlite3"))
    parser.add_argument("--vectors", type=Path, default=Path("data/knowledge/vectors.lancedb"))
    parser.add_argument("--device", choices=("cpu", "mps"), default="cpu")
    subparsers = parser.add_subparsers(dest="command", required=True)

    index = subparsers.add_parser("index", help="Index new and changed documents.")
    index.add_argument(
        "--force",
        action="store_true",
        help="Re-index every supported document, even when its content hash is unchanged.",
    )
    subparsers.add_parser("list", help="List indexed document metadata.")
    search = subparsers.add_parser("search", help="Search indexed documents.")
    search.add_argument("query")
    search.add_argument("--top-k", type=int, default=5)
    return parser


def _build_services(args: argparse.Namespace):
    config = KnowledgeConfig(
        documents_root=args.documents_root,
        metadata_path=args.metadata,
        vectors_path=args.vectors,
    ).resolved()
    parsers = ParserRegistry([TextParser(), MarkdownParser(), PDFParser()])
    scanner = DocumentScanner(config.supported_extensions)
    metadata = MetadataRepository(config.metadata_path)
    vectors = LanceVectorRepository(config.vectors_path)
    embedder: EmbeddingProvider = QwenEmbeddingProvider(device=args.device)
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
    return config, scanner, metadata, indexer, service


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

    config, scanner, metadata, indexer, service = _build_services(args)
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
        elif args.command == "search":
            print(json.dumps([
                result.__dict__ for result in service.search_documents(args.query, args.top_k)
            ], ensure_ascii=False, indent=2))
    finally:
        metadata.close()


if __name__ == "__main__":
    main()
