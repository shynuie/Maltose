"""Translate filesystem watcher events into metadata and indexing actions."""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum
from pathlib import Path
from typing import Protocol

from maltose.knowledge.queue import IndexJob, IndexingQueue
from maltose.knowledge.repositories.base import VectorRepository
from maltose.knowledge.repositories.metadata import MetadataRepository
from maltose.knowledge.watcher import DocumentWatchEvent, DocumentWatchEventType


class DocumentEventAction(StrEnum):
    ENQUEUED = "enqueued"
    MOVED = "moved"
    DELETED = "deleted"
    IGNORED = "ignored"


@dataclass(frozen=True)
class DocumentEventResult:
    action: DocumentEventAction
    path: Path
    document_id: str | None = None
    job: IndexJob | None = None


class VectorCleanup(Protocol):
    def list_document_ids(self) -> set[str]:
        ...

    def delete_document(self, document_id: str) -> None:
        ...


class DocumentEventDispatcher:
    """Apply watcher events without embedding or parsing in the watcher path."""

    def __init__(
        self,
        *,
        metadata: MetadataRepository,
        queue: IndexingQueue,
        vectors: VectorCleanup | VectorRepository,
        max_attempts: int = 3,
    ) -> None:
        if max_attempts < 1:
            raise ValueError("max_attempts must be at least 1")
        self.metadata = metadata
        self.queue = queue
        self.vectors = vectors
        self.max_attempts = max_attempts

    def dispatch(self, event: DocumentWatchEvent) -> DocumentEventResult:
        if event.type in (DocumentWatchEventType.CREATED, DocumentWatchEventType.MODIFIED):
            if event.scanned_file is None:
                raise ValueError(f"{event.type.value} event requires scanned_file")
            document_id = self.metadata.upsert_scanned_file(
                event.scanned_file,
                status="pending_index",
            )
            job = self.queue.enqueue(event.scanned_file, max_attempts=self.max_attempts)
            return DocumentEventResult(
                action=DocumentEventAction.ENQUEUED,
                path=event.path,
                document_id=document_id,
                job=job,
            )

        if event.type is DocumentWatchEventType.MOVED:
            if event.previous_path is None or event.scanned_file is None:
                raise ValueError("moved event requires previous_path and scanned_file")
            existing = self.metadata.get_by_path(event.previous_path)
            if existing is None:
                # A watcher may start after metadata was created elsewhere.
                document_id = self.metadata.upsert_scanned_file(
                    event.scanned_file,
                    status="pending_index",
                )
                job = self.queue.enqueue(event.scanned_file, max_attempts=self.max_attempts)
                return DocumentEventResult(
                    action=DocumentEventAction.ENQUEUED,
                    path=event.path,
                    document_id=document_id,
                    job=job,
                )
            self.metadata.update_path(existing["id"], event.path)
            return DocumentEventResult(
                action=DocumentEventAction.MOVED,
                path=event.path,
                document_id=existing["id"],
            )

        if event.type is DocumentWatchEventType.DELETED:
            document_id = self.metadata.mark_deleted_path(event.path)
            if document_id is None:
                return DocumentEventResult(DocumentEventAction.IGNORED, event.path)
            self.vectors.delete_document(document_id)
            return DocumentEventResult(
                action=DocumentEventAction.DELETED,
                path=event.path,
                document_id=document_id,
            )

        raise ValueError(f"Unsupported document event: {event.type}")
