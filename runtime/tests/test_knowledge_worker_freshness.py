from __future__ import annotations

import tempfile
import unittest
from datetime import datetime, timezone
from pathlib import Path

from myagent.knowledge.indexer import IndexResult
from myagent.knowledge.models import ScannedFile
from myagent.knowledge.queue import InMemoryIndexingQueue
from myagent.knowledge.worker import IndexingWorker


class KnowledgeWorkerFreshnessTests(unittest.TestCase):
    def test_stale_job_is_superseded_without_indexing_old_content(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            scanned = ScannedFile(
                path=Path(directory) / "note.txt", relative_path="note.txt",
                filename="note.txt", file_type=".txt", content_hash="old",
                file_size=3, modified_at=datetime.now(timezone.utc),
            )
            queue = InMemoryIndexingQueue()
            queue.enqueue(scanned)
            indexed: list[object] = []
            worker = IndexingWorker(
                queue,
                type("Indexer", (), {"index": lambda self, value: indexed.append(value) or IndexResult("id", 1, "indexed")})(),
                freshness_checker=lambda _: None,
            )
            worker.run_once()
            self.assertEqual(indexed, [])
            self.assertEqual(queue.list_jobs()[0].result.status, "superseded")


if __name__ == "__main__":
    unittest.main()
