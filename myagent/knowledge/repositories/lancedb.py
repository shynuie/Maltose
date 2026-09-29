"""LanceDB vector repository for the Document Knowledge Base.

This repository deliberately uses its own database path and table names. It
must never point at the existing Memory LanceDB path.
"""

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from uuid import uuid4

from myagent.knowledge.models import DocumentChunk


class LanceVectorRepository:
    summary_table_name = "document_summaries"
    chunk_table_name = "document_chunks"

    def __init__(self, path: str | Path = "data/knowledge/vectors.lancedb") -> None:
        try:
            import lancedb
        except ImportError as exc:
            raise RuntimeError(
                "KDB LanceDB storage requires the 'vector-memory' extra. "
                "Install it with: uv sync --extra vector-memory"
            ) from exc
        self.path = Path(path)
        self._db = lancedb.connect(str(self.path))

    def _table(self, name: str):
        if name not in self._db.list_tables().tables:
            return None
        return self._db.open_table(name)

    def _write_rows(self, name: str, rows: list[dict]) -> None:
        if not rows:
            return
        table = self._table(name)
        if table is None:
            self._db.create_table(name, data=rows)
        else:
            table.add(rows)

    def replace_document(
        self,
        document_id: str,
        *,
        summary: str,
        summary_embedding: list[float],
        chunks: list[tuple[DocumentChunk, list[float]]],
    ) -> None:
        """Replace a document's vector rows before metadata becomes indexed.

        Metadata is marked indexed only after this method returns. If a write
        fails, the caller marks the document as indexing_failed and the old
        metadata remains authoritative for retrieval decisions.
        """
        self._delete_document_rows(document_id)
        now = datetime.now(timezone.utc).isoformat()
        self._write_rows(
            self.summary_table_name,
            [
                {
                    "id": document_id,
                    "document_id": document_id,
                    "summary": summary,
                    "embedding": summary_embedding,
                    "updated_at": now,
                }
            ],
        )
        self._write_rows(
            self.chunk_table_name,
            [self._chunk_row(document_id, chunk, embedding) for chunk, embedding in chunks],
        )

    def delete_document(self, document_id: str) -> None:
        """Remove summary and chunk vectors for a deleted source document."""
        self._delete_document_rows(document_id)

    def list_document_ids(self) -> set[str]:
        """List ids from both vector tables for repair/orphan detection."""
        document_ids: set[str] = set()
        for name in (self.summary_table_name, self.chunk_table_name):
            table = self._table(name)
            if table is None:
                continue
            rows = table.to_arrow().column("document_id").to_pylist()
            document_ids.update(str(document_id) for document_id in rows)
        return document_ids

    def _delete_document_rows(self, document_id: str) -> None:
        escaped = document_id.replace("'", "''")
        for name in (self.summary_table_name, self.chunk_table_name):
            table = self._table(name)
            if table is not None:
                table.delete(f"document_id = '{escaped}'")

    def search_summaries(self, embedding: list[float], limit: int) -> list[dict]:
        table = self._table(self.summary_table_name)
        if table is None:
            return []
        rows = table.search(embedding).distance_type("cosine").limit(limit).to_list()
        return [self._with_similarity(row) for row in rows]

    def search_chunks(
        self,
        document_ids: list[str],
        embedding: list[float],
        limit: int,
    ) -> list[dict]:
        table = self._table(self.chunk_table_name)
        if table is None or not document_ids:
            return []
        escaped_ids = ", ".join(f"'{document_id.replace(chr(39), chr(39) * 2)}'" for document_id in document_ids)
        rows = (
            table.search(embedding)
            .distance_type("cosine")
            .where(f"document_id IN ({escaped_ids})")
            .limit(limit)
            .to_list()
        )
        return [self._with_similarity(row) for row in rows]

    @staticmethod
    def _with_similarity(row: dict) -> dict:
        result = dict(row)
        distance = result.pop("_distance", None)
        if isinstance(distance, (int, float)):
            result["similarity_score"] = 1.0 - float(distance)
        return result

    @staticmethod
    def _chunk_row(
        document_id: str,
        chunk: DocumentChunk,
        embedding: list[float],
    ) -> dict:
        return {
            "id": f"{document_id}:{chunk.chunk_index}:{uuid4().hex}",
            "document_id": document_id,
            "chunk_index": chunk.chunk_index,
            "text_preview": chunk.text,
            "page": chunk.page,
            "section": chunk.section,
            "start_offset": chunk.start_offset,
            "end_offset": chunk.end_offset,
            "embedding": embedding,
            "metadata_json": json.dumps(chunk.metadata, ensure_ascii=False),
        }
