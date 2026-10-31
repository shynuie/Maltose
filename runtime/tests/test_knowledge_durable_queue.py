from __future__ import annotations

import tempfile
import unittest
from datetime import datetime, timezone
from pathlib import Path

from maltose.knowledge.indexer import IndexResult
from maltose.knowledge.models import ScannedFile
from maltose.knowledge.queue import IndexJobStatus, SQLiteIndexingQueue


def make_scanned(path: Path) -> ScannedFile:
    return ScannedFile(
        path=path,
        relative_path=path.name,
        filename=path.name,
        file_type="txt",
        content_hash="hash",
        file_size=4,
        modified_at=datetime.now(timezone.utc),
    )


class SQLiteIndexingQueueTests(unittest.TestCase):
    def test_job_survives_close_and_reopens_as_queued(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            queue_path = Path(directory) / "queue.sqlite3"
            first = SQLiteIndexingQueue(queue_path)
            job = first.enqueue(make_scanned(Path(directory) / "note.txt"))
            claimed = first.claim()
            self.assertEqual(claimed.status, IndexJobStatus.RUNNING)
            first.close()

            second = SQLiteIndexingQueue(queue_path)
            recovered = second.claim()

            self.assertEqual(recovered.job_id, job.job_id)
            self.assertEqual(recovered.status, IndexJobStatus.RUNNING)
            self.assertEqual(recovered.attempts, 2)
            second.complete(job.job_id, IndexResult("doc-1", 1, "indexed"))
            second.close()

    def test_failed_job_and_result_are_persisted(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            queue_path = Path(directory) / "queue.sqlite3"
            queue = SQLiteIndexingQueue(queue_path)
            job = queue.enqueue(make_scanned(Path(directory) / "note.txt"), max_attempts=1)
            queue.claim()
            failed = queue.fail(job.job_id, "bad source")
            queue.close()

            reopened = SQLiteIndexingQueue(queue_path)
            stored = reopened.get(job.job_id)
            self.assertEqual(failed.status, IndexJobStatus.FAILED)
            self.assertEqual(stored.last_error, "bad source")
            self.assertEqual(stored.error_history, ["bad source"])
            reopened.close()


if __name__ == "__main__":
    unittest.main()
