"""Hierarchical document retrieval and source read-back."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from maltose.knowledge.embeddings import EmbeddingProvider
from maltose.knowledge.models import DocumentLocation
from maltose.knowledge.repositories.base import VectorRepository
from maltose.knowledge.repositories.metadata import MetadataRepository
from maltose.knowledge.source_reader import SourceContent, SourceReader


@dataclass(frozen=True)
class DocumentSearchResult:
    document_id: str
    title: str | None
    path: str
    summary: str | None
    similarity_score: float | None
    metadata: dict[str, Any]


@dataclass(frozen=True)
class ChunkSearchResult:
    document_id: str
    chunk_id: str
    page: int | None
    section: str | None
    start_offset: int | None
    end_offset: int | None
    similarity_score: float | None
    preview: str | None


class DocumentKnowledgeService:
    def __init__(
        self,
        *,
        metadata: MetadataRepository,
        vectors: VectorRepository,
        embedder: EmbeddingProvider,
        source_reader: SourceReader,
    ) -> None:
        self.metadata = metadata
        self.vectors = vectors
        self.embedder = embedder
        self.source_reader = source_reader

    def search_documents(self, query: str, top_k: int = 5) -> list[DocumentSearchResult]:
        query = self._validate_query(query)
        rows = self.vectors.search_summaries(self.embedder.embed(query), max(1, top_k))
        results: list[DocumentSearchResult] = []
        for row in rows:
            record = self.metadata.get_by_id(row["document_id"])
            if record is None or record.get("status") != "indexed":
                continue
            results.append(
                DocumentSearchResult(
                    document_id=record["id"],
                    title=record.get("title"),
                    path=record["path"],
                    summary=record.get("summary"),
                    similarity_score=row.get("similarity_score"),
                    metadata=self._metadata(record),
                )
            )
        return results

    def search_in_document(
        self,
        document_id: str,
        query: str,
        top_k: int = 10,
    ) -> list[ChunkSearchResult]:
        if self.metadata.get_by_id(document_id) is None:
            raise KeyError(f"Unknown document: {document_id}")
        query = self._validate_query(query)
        rows = self.vectors.search_chunks([document_id], self.embedder.embed(query), max(1, top_k))
        return [
            ChunkSearchResult(
                document_id=row["document_id"],
                chunk_id=row["id"],
                page=row.get("page"),
                section=row.get("section"),
                start_offset=row.get("start_offset"),
                end_offset=row.get("end_offset"),
                similarity_score=row.get("similarity_score"),
                preview=row.get("text_preview"),
            )
            for row in rows
        ]

    def read_document(self, document_id: str, location: DocumentLocation | None = None) -> SourceContent:
        return self.source_reader.read(document_id, location)

    @staticmethod
    def _validate_query(query: str) -> str:
        query = query.strip()
        if not query:
            raise ValueError("Document query cannot be empty")
        return query

    @staticmethod
    def _metadata(record: dict[str, Any]) -> dict[str, Any]:
        return {
            "source_type": "truth",
            "collection": record.get("collection"),
            "file_type": record.get("file_type"),
            "content_hash": record.get("content_hash"),
            "metadata_json": record.get("metadata_json", "{}"),
        }
