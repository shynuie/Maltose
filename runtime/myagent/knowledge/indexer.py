"""Dependency-injected indexing orchestration."""

from __future__ import annotations

from dataclasses import dataclass
import logging

from myagent.knowledge.chunker import DocumentChunker
from myagent.knowledge.embeddings import EmbeddingProvider
from myagent.knowledge.models import DocumentChunk, ParsedDocument, ScannedFile
from myagent.knowledge.parsers.base import ParserRegistry
from myagent.knowledge.repositories.base import VectorRepository
from myagent.knowledge.repositories.metadata import MetadataRepository
from myagent.knowledge.summarizer import DocumentSummarizer

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class IndexResult:
    document_id: str
    chunk_count: int
    status: str


class DocumentIndexer:
    def __init__(
        self,
        *,
        parsers: ParserRegistry,
        chunker: DocumentChunker,
        summarizer: DocumentSummarizer,
        embedder: EmbeddingProvider,
        metadata: MetadataRepository,
        vectors: VectorRepository,
    ) -> None:
        self.parsers = parsers
        self.chunker = chunker
        self.summarizer = summarizer
        self.embedder = embedder
        self.metadata = metadata
        self.vectors = vectors

    def index(self, scanned: ScannedFile) -> IndexResult:
        logger.info(
            "kdb_index_started path=%s hash=%s",
            scanned.path,
            scanned.content_hash[:12],
        )
        document_id = self.metadata.upsert_scanned_file(scanned, status="indexing")
        try:
            logger.info("kdb_index_stage document_id=%s stage=parse", document_id)
            document = self.parsers.parse(scanned.path)
            logger.info("kdb_index_stage document_id=%s stage=summary", document_id)
            summary = self.summarizer.summarize(document).strip()
            if not summary:
                raise ValueError(f"Summary provider returned empty text: {scanned.path}")
            logger.info("kdb_index_stage document_id=%s stage=chunk", document_id)
            chunks = self.chunker.chunk(document)
            logger.info(
                "kdb_index_stage document_id=%s stage=embedding chunks=%d",
                document_id,
                len(chunks),
            )
            embedded_chunks = [(chunk, self.embedder.embed(chunk.text)) for chunk in chunks]
            summary_embedding = self.embedder.embed(summary)
            logger.info("kdb_index_stage document_id=%s stage=vector_persist", document_id)
            self.vectors.replace_document(
                document_id,
                summary=summary,
                summary_embedding=summary_embedding,
                chunks=embedded_chunks,
            )
            self.metadata.mark_indexed(document_id, title=document.title, summary=summary)
            result = IndexResult(document_id, len(chunks), "indexed")
            logger.info(
                "kdb_index_completed document_id=%s status=%s chunks=%d",
                document_id,
                result.status,
                result.chunk_count,
            )
            return result
        except Exception:
            self.metadata.mark_indexing_failed(document_id)
            logger.exception("kdb_index_failed document_id=%s path=%s", document_id, scanned.path)
            raise
