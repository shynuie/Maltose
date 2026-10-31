from __future__ import annotations

import tempfile
import unittest
from datetime import datetime, timezone
from pathlib import Path

from maltose.knowledge.indexer import IndexResult
from maltose.knowledge.models import ScannedFile
from maltose.knowledge.queue import IndexJobStatus, InMemoryIndexingQueue


def make_scanned_file(path: Path) -> ScannedFile:
    return ScannedFile(
        path=path,
        relative_path=path.name,
        filename=path.name,
        file_type=path.suffix.lstrip("."),
        content_hash="abc123",
        file_size=3,
        modified_at=datetime.now(timezone.utc),
    )


class InMemoryIndexingQueueTests(unittest.TestCase):
    def test_claim_and_complete_transitions_job(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            queue = InMemoryIndexingQueue()
            job = queue.enqueue(make_scanned_file(Path(directory) / "note.txt"))

            claimed = queue.claim()
            self.assertIs(claimed, job)
            self.assertEqual(job.status, IndexJobStatus.RUNNING)
            self.assertEqual(job.attempts, 1)

            result = IndexResult("doc-1", 2, "indexed")
            completed = queue.complete(job.job_id, result)
            self.assertEqual(completed.status, IndexJobStatus.SUCCEEDED)
            self.assertEqual(completed.result, result)
            self.assertIsNone(queue.claim())

    def test_failure_requeues_until_max_attempts_then_fails(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            queue = InMemoryIndexingQueue()
            job = queue.enqueue(
                make_scanned_file(Path(directory) / "note.txt"),
                max_attempts=2,
            )

            first = queue.claim()
            self.assertIsNotNone(first)
            queue.fail(job.job_id, "temporary error")
            self.assertEqual(job.status, IndexJobStatus.QUEUED)
            self.assertEqual(job.error_history, ["temporary error"])

            second = queue.claim()
            self.assertIs(second, job)
            queue.fail(job.job_id, RuntimeError("permanent error"))
            self.assertEqual(job.status, IndexJobStatus.FAILED)
            self.assertEqual(job.attempts, 2)
            self.assertEqual(job.last_error, "permanent error")
            self.assertIsNone(queue.claim())

    def test_invalid_state_transitions_are_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            queue = InMemoryIndexingQueue()
            job = queue.enqueue(make_scanned_file(Path(directory) / "note.txt"))
            with self.assertRaises(ValueError):
                queue.complete(job.job_id, IndexResult("doc-1", 0, "indexed"))
            with self.assertRaises(KeyError):
                queue.fail("missing", "error")


if __name__ == "__main__":
    unittest.main()
