from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from maltose.knowledge.event_dispatcher import DocumentEventAction, DocumentEventDispatcher
from maltose.knowledge.models import ScannedFile
from maltose.knowledge.queue import InMemoryIndexingQueue
from maltose.knowledge.repositories.metadata import MetadataRepository
from maltose.knowledge.watcher import DocumentWatchEvent, DocumentWatchEventType


class FakeVectors:
    def __init__(self) -> None:
        self.deleted: list[str] = []

    def delete_document(self, document_id: str) -> None:
        self.deleted.append(document_id)


def scanned(path: Path, content_hash: str = "hash") -> ScannedFile:
    from datetime import datetime, timezone

    return ScannedFile(
        path=path,
        relative_path=path.name,
        filename=path.name,
        file_type="txt",
        content_hash=content_hash,
        file_size=1,
        modified_at=datetime.now(timezone.utc),
    )


class DocumentEventDispatcherTests(unittest.TestCase):
    def test_create_and_modify_enqueue_indexing_job(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            metadata = MetadataRepository(root / "metadata.sqlite3")
            queue = InMemoryIndexingQueue()
            dispatcher = DocumentEventDispatcher(
                metadata=metadata,
                queue=queue,
                vectors=FakeVectors(),
            )
            path = root / "note.txt"
            path.write_text("one", encoding="utf-8")
            event = DocumentWatchEvent(
                DocumentWatchEventType.CREATED,
                path,
                scanned_file=scanned(path),
            )

            result = dispatcher.dispatch(event)

            self.assertEqual(result.action, DocumentEventAction.ENQUEUED)
            self.assertIsNotNone(result.job)
            self.assertEqual(metadata.get_by_path(path)["status"], "pending_index")
            metadata.close()

    def test_move_preserves_document_identity_without_reindexing(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            old_path = root / "note.txt"
            new_path = root / "archive" / "note.txt"
            new_path.parent.mkdir()
            metadata = MetadataRepository(root / "metadata.sqlite3")
            queue = InMemoryIndexingQueue()
            vectors = FakeVectors()
            dispatcher = DocumentEventDispatcher(metadata=metadata, queue=queue, vectors=vectors)
            document_id = metadata.upsert_scanned_file(scanned(old_path), status="indexed")

            result = dispatcher.dispatch(
                DocumentWatchEvent(
                    DocumentWatchEventType.MOVED,
                    new_path,
                    scanned_file=scanned(new_path),
                    previous_path=old_path,
                    previous_hash="hash",
                )
            )

            self.assertEqual(result.action, DocumentEventAction.MOVED)
            self.assertEqual(result.document_id, document_id)
            self.assertEqual(metadata.get_by_id(document_id)["path"], str(new_path))
            self.assertIsNone(queue.claim())
            metadata.close()

    def test_delete_soft_deletes_metadata_and_removes_vectors(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            path = root / "note.txt"
            metadata = MetadataRepository(root / "metadata.sqlite3")
            queue = InMemoryIndexingQueue()
            vectors = FakeVectors()
            dispatcher = DocumentEventDispatcher(metadata=metadata, queue=queue, vectors=vectors)
            document_id = metadata.upsert_scanned_file(scanned(path), status="indexed")

            result = dispatcher.dispatch(DocumentWatchEvent(DocumentWatchEventType.DELETED, path))

            self.assertEqual(result.action, DocumentEventAction.DELETED)
            self.assertEqual(metadata.get_by_id(document_id)["status"], "deleted")
            self.assertEqual(vectors.deleted, [document_id])
            metadata.close()


if __name__ == "__main__":
    unittest.main()
