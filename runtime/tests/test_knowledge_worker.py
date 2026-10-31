from __future__ import annotations

import tempfile
import time
import unittest
from datetime import datetime, timezone
from pathlib import Path

from myagent.knowledge.indexer import IndexResult
from myagent.knowledge.models import ScannedFile
from myagent.knowledge.queue import IndexJobStatus, InMemoryIndexingQueue
from myagent.knowledge.worker import IndexingWorker


def make_scanned_file(path: Path) -> ScannedFile:
    return ScannedFile(
        path=path,
        relative_path=path.name,
        filename=path.name,
        file_type="txt",
        content_hash="abc123",
        file_size=3,
        modified_at=datetime.now(timezone.utc),
    )


class FakeIndexer:
    def __init__(self, failures: int = 0) -> None:
        self.failures = failures
        self.calls = 0

    def index(self, scanned_file: ScannedFile) -> IndexResult:
        self.calls += 1
        if self.calls <= self.failures:
            raise RuntimeError("temporary indexing failure")
        return IndexResult(f"doc-{self.calls}", 1, "indexed")


class IndexingWorkerTests(unittest.TestCase):
    def test_run_until_empty_indexes_and_retries_jobs(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            queue = InMemoryIndexingQueue()
            job = queue.enqueue(
                make_scanned_file(Path(directory) / "note.txt"),
                max_attempts=2,
            )
            indexer = FakeIndexer(failures=1)
            worker = IndexingWorker(queue, indexer)

            attempts = worker.run_until_empty()

            self.assertEqual(attempts, 2)
            self.assertEqual(indexer.calls, 2)
            self.assertEqual(job.status, IndexJobStatus.SUCCEEDED)
            self.assertEqual(job.attempts, 2)

    def test_background_worker_can_be_stopped(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            queue = InMemoryIndexingQueue()
            job = queue.enqueue(make_scanned_file(Path(directory) / "note.txt"))
            worker = IndexingWorker(queue, FakeIndexer(), idle_interval=0.01)

            worker.start()
            deadline = time.monotonic() + 1.0
            while job.status != IndexJobStatus.SUCCEEDED and time.monotonic() < deadline:
                time.sleep(0.01)
            worker.stop()

            self.assertEqual(job.status, IndexJobStatus.SUCCEEDED)

    def test_invalid_worker_configuration_is_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            with self.assertRaises(ValueError):
                IndexingWorker(
                    InMemoryIndexingQueue(),
                    FakeIndexer(),
                    idle_interval=0,
                )


if __name__ == "__main__":
    unittest.main()
