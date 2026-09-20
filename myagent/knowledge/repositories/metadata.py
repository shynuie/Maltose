"""SQLite metadata repository for document identity and indexing state."""

from __future__ import annotations

import json
import sqlite3
from datetime import datetime
from pathlib import Path
from typing import Any
from uuid import uuid4

from myagent.knowledge.models import ScannedFile


class MetadataRepository:
    def __init__(self, path: str | Path) -> None:
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._connection = sqlite3.connect(self.path)
        self._connection.row_factory = sqlite3.Row
        self._initialize()

    def _initialize(self) -> None:
        self._connection.execute(
            """
            CREATE TABLE IF NOT EXISTS documents (
                id TEXT PRIMARY KEY,
                path TEXT NOT NULL UNIQUE,
                filename TEXT NOT NULL,
                title TEXT,
                file_type TEXT NOT NULL,
                summary TEXT,
                content_hash TEXT NOT NULL,
                file_size INTEGER NOT NULL,
                created_at TEXT NOT NULL,
                modified_at TEXT NOT NULL,
                indexed_at TEXT,
                status TEXT NOT NULL,
                collection TEXT,
                metadata_json TEXT NOT NULL DEFAULT '{}'
            )
            """
        )
        self._connection.commit()

    def close(self) -> None:
        self._connection.close()

    def __enter__(self) -> "MetadataRepository":
        return self

    def __exit__(self, *_: object) -> None:
        self.close()

    def get_by_path(self, path: str | Path) -> dict[str, Any] | None:
        row = self._connection.execute(
            "SELECT * FROM documents WHERE path = ?", (str(Path(path)),)
        ).fetchone()
        return dict(row) if row else None

    def get_by_id(self, document_id: str) -> dict[str, Any] | None:
        row = self._connection.execute(
            "SELECT * FROM documents WHERE id = ?", (document_id,)
        ).fetchone()
        return dict(row) if row else None

    def get_by_content_hash(self, content_hash: str) -> dict[str, Any] | None:
        row = self._connection.execute(
            "SELECT * FROM documents WHERE content_hash = ? ORDER BY indexed_at DESC LIMIT 1",
            (content_hash,),
        ).fetchone()
        return dict(row) if row else None

    def update_path(self, document_id: str, path: str | Path) -> None:
        self._connection.execute(
            "UPDATE documents SET path = ?, status = 'pending_index' WHERE id = ?",
            (str(Path(path)), document_id),
        )
        self._connection.commit()

    def mark_missing(self, active_paths: set[str], *, status: str = "deleted") -> list[str]:
        rows = self._connection.execute("SELECT id, path FROM documents").fetchall()
        missing = [row["id"] for row in rows if row["path"] not in active_paths]
        if missing:
            self._connection.executemany(
                "UPDATE documents SET status = ? WHERE id = ?",
                [(status, document_id) for document_id in missing],
            )
            self._connection.commit()
        return missing

    def mark_indexed(self, document_id: str, *, title: str | None, summary: str) -> None:
        self._connection.execute(
            """
            UPDATE documents
            SET title = COALESCE(?, title), summary = ?,
                indexed_at = ?, status = 'indexed'
            WHERE id = ?
            """,
            (title, summary, datetime.now().astimezone().isoformat(), document_id),
        )
        self._connection.commit()

    def mark_indexing_failed(self, document_id: str) -> None:
        self._connection.execute(
            "UPDATE documents SET status = 'indexing_failed' WHERE id = ?",
            (document_id,),
        )
        self._connection.commit()

    def upsert_scanned_file(
        self,
        scanned: ScannedFile,
        *,
        title: str | None = None,
        collection: str | None = None,
        metadata: dict[str, Any] | None = None,
        status: str = "pending_index",
    ) -> str:
        existing = self.get_by_path(scanned.path)
        document_id = existing["id"] if existing else f"doc_{uuid4().hex}"
        created_at = existing["created_at"] if existing else datetime.now().astimezone().isoformat()
        self._connection.execute(
            """
            INSERT INTO documents (
                id, path, filename, title, file_type, summary, content_hash,
                file_size, created_at, modified_at, indexed_at, status,
                collection, metadata_json
            ) VALUES (?, ?, ?, ?, ?, NULL, ?, ?, ?, ?, NULL, ?, ?, ?)
            ON CONFLICT(path) DO UPDATE SET
                filename = excluded.filename,
                title = COALESCE(excluded.title, documents.title),
                file_type = excluded.file_type,
                content_hash = excluded.content_hash,
                file_size = excluded.file_size,
                modified_at = excluded.modified_at,
                status = excluded.status,
                collection = COALESCE(excluded.collection, documents.collection),
                metadata_json = excluded.metadata_json
            """,
            (
                document_id,
                str(scanned.path),
                scanned.filename,
                title,
                scanned.file_type,
                scanned.content_hash,
                scanned.file_size,
                created_at,
                scanned.modified_at.isoformat(),
                status,
                collection,
                json.dumps(metadata or {}, ensure_ascii=False),
            ),
        )
        self._connection.commit()
        return document_id

    def list_documents(self, *, status: str | None = None) -> list[dict[str, Any]]:
        if status is None:
            rows = self._connection.execute("SELECT * FROM documents ORDER BY path").fetchall()
        else:
            rows = self._connection.execute(
                "SELECT * FROM documents WHERE status = ? ORDER BY path", (status,)
            ).fetchall()
        return [dict(row) for row in rows]
