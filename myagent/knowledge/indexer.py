"""Dependency-injected indexing orchestration."""

from __future__ import annotations

from dataclasses import dataclass

from myagent.knowledge.chunker import DocumentChunker
from myagent.knowledge.embeddings import EmbeddingProvider
from myagent.knowledge.models import DocumentChunk, ParsedDocument, ScannedFile
from myagent.knowledge.parsers.base import ParserRegistry
from myagent.knowledge.repositories.base import VectorRepository
from myagent.knowledge.repositories.metadata import MetadataRepository
from myagent.knowledge.summarizer import DocumentSummarizer


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
        document_id = self.metadata.upsert_scanned_file(scanned, status="indexing")
        try:
            document = self.parsers.parse(scanned.path)
            summary = self.summarizer.summarize(document).strip()
            if not summary:
                raise ValueError(f"Summary provider returned empty text: {scanned.path}")
            chunks = self.chunker.chunk(document)
            embedded_chunks = [(chunk, self.embedder.embed(chunk.text)) for chunk in chunks]
            summary_embedding = self.embedder.embed(summary)
            self.vectors.replace_document(
                document_id,
                summary=summary,
                summary_embedding=summary_embedding,
                chunks=embedded_chunks,
            )
            self.metadata.mark_indexed(document_id, title=document.title, summary=summary)
            return IndexResult(document_id, len(chunks), "indexed")
        except Exception:
            self.metadata.mark_indexing_failed(document_id)
            raise
