from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from maltose.filesystem.events import FilesystemMutationEvent, FilesystemMutationType
from maltose.knowledge.mutation import DocumentMutationCoordinator
from maltose.knowledge.queue import SQLiteIndexingQueue
from maltose.knowledge.models import ScannedFile
from datetime import datetime, timezone


class FakeScanner:
    def __init__(self, scanned):
        self.scanned = scanned

    def scan(self, root):
        return type("ScanResult", (), {"files": self.scanned})()


class FakeIndexer:
    def index(self, scanned):
        return {"indexed": str(scanned.path)}


class FakeMetadata:
    def mark_deleted_path(self, path):
        return f"deleted:{path.name}"


class FilesystemKDBEventTests(unittest.TestCase):
    def test_document_mutation_reindexes_only_events_under_documents_root(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory) / "documents"
            root.mkdir()
            path = root / "note.md"
            path.write_text("note", encoding="utf-8")
            scanned = type("Scanned", (), {"path": path})()
            coordinator = DocumentMutationCoordinator(
                documents_root=root,
                scanner=FakeScanner([scanned]),
                indexer=FakeIndexer(),
                metadata=FakeMetadata(),
            )

            result = coordinator.handle(FilesystemMutationEvent(
                FilesystemMutationType.MODIFIED, "documents", path, "note.md"
            ))

            self.assertEqual(result["indexed"], str(path))

    def test_trash_marks_metadata_and_wrong_root_is_ignored(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory) / "documents"
            root.mkdir()
            path = root / "note.md"
            coordinator = DocumentMutationCoordinator(
                documents_root=root,
                scanner=FakeScanner([]),
                indexer=FakeIndexer(),
                metadata=FakeMetadata(),
            )
            deleted = coordinator.handle(FilesystemMutationEvent(
                FilesystemMutationType.TRASHED, "documents", path, "note.md"
            ))
            ignored = coordinator.handle(FilesystemMutationEvent(
                FilesystemMutationType.MODIFIED, "workspace", path, "note.md"
            ))
            self.assertEqual(deleted, "deleted:note.md")
            self.assertIsNone(ignored)

    def test_mutation_can_enqueue_durable_index_job_for_later_worker(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory) / "documents"
            root.mkdir()
            path = root / "note.md"
            path.write_text("note", encoding="utf-8")
            scanned = ScannedFile(
                path=path,
                relative_path="note.md",
                filename="note.md",
                file_type=".md",
                content_hash="hash",
                file_size=4,
                modified_at=datetime.now(timezone.utc),
            )
            queue = SQLiteIndexingQueue(Path(directory) / "queue.sqlite3")
            coordinator = DocumentMutationCoordinator(
                documents_root=root,
                scanner=FakeScanner([scanned]),
                indexer=FakeIndexer(),
                metadata=FakeMetadata(),
                queue=queue,
            )
            job = coordinator.handle(FilesystemMutationEvent(
                FilesystemMutationType.MODIFIED, "documents", path, "note.md"
            ))
            self.assertEqual(job.status.value, "queued")
            queue.close()
            recovered = SQLiteIndexingQueue(Path(directory) / "queue.sqlite3")
            self.assertEqual(recovered.list_jobs()[0].scanned_file.content_hash, "hash")
            recovered.close()


if __name__ == "__main__":
    unittest.main()
