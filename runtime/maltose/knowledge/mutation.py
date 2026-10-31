"""Bridge filesystem mutation events to document indexing responsibilities."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from maltose.filesystem.events import FilesystemMutationEvent, FilesystemMutationType
from maltose.filesystem.metrics import FilesystemRuntimeMetrics
from maltose.knowledge.indexer import DocumentIndexer, IndexResult
from maltose.knowledge.queue import IndexJob, IndexingQueue
from maltose.knowledge.repositories.metadata import MetadataRepository
from maltose.knowledge.scanner import DocumentScanner


class DocumentMutationCoordinator:
    """Re-index only source documents; never writes filesystem data itself."""

    def __init__(
        self,
        *,
        documents_root: str | Path,
        scanner: DocumentScanner,
        indexer: DocumentIndexer,
        metadata: MetadataRepository,
        filesystem_root_name: str = "documents",
        queue: IndexingQueue | None = None,
        max_attempts: int = 3,
        metrics: FilesystemRuntimeMetrics | None = None,
    ) -> None:
        self.documents_root = Path(documents_root).expanduser().resolve()
        self.scanner = scanner
        self.indexer = indexer
        self.metadata = metadata
        self.filesystem_root_name = filesystem_root_name
        self.queue = queue
        if max_attempts < 1:
            raise ValueError("max_attempts must be positive.")
        self.max_attempts = max_attempts
        self.metrics = metrics or FilesystemRuntimeMetrics()

    def handle(self, event: FilesystemMutationEvent) -> IndexResult | IndexJob | str | None:
        if event.root != self.filesystem_root_name:
            self.metrics.increment("events_ignored")
            return None
        try:
            event.path.resolve().relative_to(self.documents_root)
        except ValueError:
            raise PermissionError("Filesystem mutation is outside the documents root.")
        if event.type in {
            FilesystemMutationType.CREATED,
            FilesystemMutationType.MODIFIED,
            FilesystemMutationType.COPIED,
            FilesystemMutationType.RESTORED,
            FilesystemMutationType.MOVED,
        }:
            self.metrics.increment("events_received")
            if event.type == FilesystemMutationType.MOVED and event.source_root == self.filesystem_root_name:
                if event.source_path is not None:
                    self.metadata.mark_deleted_path(self.documents_root / event.source_path)
                    self.metrics.increment("documents_deleted")
            scanned = next(
                (item for item in self.scanner.scan(self.documents_root).files if item.path == event.path),
                None,
            )
            if scanned is None:
                self.metrics.increment("events_failed")
                raise FileNotFoundError(event.path)
            if self.queue is not None:
                job = self.queue.enqueue(scanned, max_attempts=self.max_attempts)
                self.metrics.increment("jobs_enqueued")
                return job
            try:
                result = self.indexer.index(scanned)
            except Exception:
                self.metrics.increment("index_failures")
                raise
            self.metrics.increment("documents_indexed")
            return result
        if event.type == FilesystemMutationType.TRASHED:
            result = self.metadata.mark_deleted_path(event.path)
            self.metrics.increment("documents_deleted")
            return result
        return None
