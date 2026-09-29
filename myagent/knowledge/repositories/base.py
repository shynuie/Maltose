"""Repository protocols used by the indexing coordinator."""

from __future__ import annotations

from typing import Protocol

from myagent.knowledge.models import DocumentChunk


class VectorRepository(Protocol):
    def list_document_ids(self) -> set[str]:
        """Return document ids currently represented in vector storage."""
        ...

    def delete_document(self, document_id: str) -> None:
        """Delete all vector rows belonging to a document."""
        ...

    def replace_document(
        self,
        document_id: str,
        *,
        summary: str,
        summary_embedding: list[float],
        chunks: list[tuple[DocumentChunk, list[float]]],
    ) -> None:
        """Atomically replace all vector records belonging to a document."""
        ...

    def search_summaries(self, embedding: list[float], limit: int) -> list[dict]:
        ...

    def search_chunks(
        self,
        document_ids: list[str],
        embedding: list[float],
        limit: int,
    ) -> list[dict]:
        ...
