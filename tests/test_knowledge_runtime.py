from __future__ import annotations

import tempfile
import time
import unittest
from pathlib import Path

from myagent.knowledge.event_dispatcher import DocumentEventDispatcher
from myagent.knowledge.queue import InMemoryIndexingQueue, IndexJobStatus
from myagent.knowledge.repositories.metadata import MetadataRepository
from myagent.knowledge.runtime import KnowledgeRuntime
from myagent.knowledge.scanner import DocumentScanner
from myagent.knowledge.watcher import PollingDocumentWatcher
from myagent.knowledge.worker import IndexingWorker
from tests.test_knowledge_worker import FakeIndexer
from tests.test_knowledge_event_dispatcher import FakeVectors


class KnowledgeRuntimeTests(unittest.TestCase):
    def make_runtime(self, root: Path):
        metadata = MetadataRepository(root / "metadata.sqlite3")
        queue = InMemoryIndexingQueue()
        watcher = PollingDocumentWatcher(root, DocumentScanner())
        dispatcher = DocumentEventDispatcher(
            metadata=metadata,
            queue=queue,
            vectors=FakeVectors(),
        )
        indexer = FakeIndexer()
        worker = IndexingWorker(queue, indexer, idle_interval=0.01)
        runtime = KnowledgeRuntime(
            watcher=watcher,
            dispatcher=dispatcher,
            queue=queue,
            worker=worker,
            poll_interval=0.01,
        )
        return runtime, queue, metadata, indexer

    def test_poll_once_connects_file_event_to_indexer(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            runtime, queue, metadata, _ = self.make_runtime(root)
            runtime.watcher.start()
            path = root / "note.txt"
            path.write_text("hello", encoding="utf-8")

            cycle = runtime.poll_once()

            self.assertEqual(len(cycle.events), 1)
            self.assertEqual(cycle.worker_attempts, 1)
            self.assertEqual(len(cycle.dispatched), 1)
            document_id = cycle.dispatched[0].document_id
            self.assertEqual(metadata.get_by_id(document_id)["status"], "pending_index")
            self.assertEqual(queue.get(cycle.dispatched[0].job.job_id).status, IndexJobStatus.SUCCEEDED)
            metadata.close()

    def test_background_runtime_can_detect_and_index_file(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            runtime, queue, metadata, indexer = self.make_runtime(root)
            runtime.start()
            path = root / "note.txt"
            path.write_text("hello", encoding="utf-8")
            deadline = time.monotonic() + 1.0
            while indexer.calls == 0 and time.monotonic() < deadline:
                time.sleep(0.01)
            runtime.stop()

            self.assertEqual(indexer.calls, 1)
            self.assertIsNone(queue.claim())
            metadata.close()

    def test_invalid_poll_interval_is_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            runtime, _, metadata, _ = self.make_runtime(Path(directory))
            with self.assertRaises(ValueError):
                KnowledgeRuntime(
                    watcher=runtime.watcher,
                    dispatcher=runtime.dispatcher,
                    queue=runtime.queue,
                    worker=runtime.worker,
                    poll_interval=0,
                )
            metadata.close()


if __name__ == "__main__":
    unittest.main()
