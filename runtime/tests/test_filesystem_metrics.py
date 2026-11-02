from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from maltose.filesystem.events import FilesystemMutationEvent, FilesystemMutationType
from maltose.filesystem.metrics import FilesystemRuntimeMetrics
from maltose.knowledge.mutation import DocumentMutationCoordinator


class FilesystemMetricsTests(unittest.TestCase):
    def test_coordinator_reports_event_outcomes(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory) / "documents"
            root.mkdir()
            path = root / "note.md"
            path.write_text("note", encoding="utf-8")
            scanned = type("Scanned", (), {"path": path})()
            metrics = FilesystemRuntimeMetrics()
            coordinator = DocumentMutationCoordinator(
                documents_root=root,
                scanner=type("Scanner", (), {"scan": lambda self, _: type("Result", (), {"files": [scanned]})()})(),
                indexer=type("Indexer", (), {"index": lambda self, _: {"ok": True}})(),
                metadata=type("Metadata", (), {"mark_deleted_path": lambda self, _: "deleted"})(),
                metrics=metrics,
            )
            coordinator.handle(FilesystemMutationEvent(
                FilesystemMutationType.MODIFIED, "documents", path, "note.md"
            ))
            coordinator.handle(FilesystemMutationEvent(
                FilesystemMutationType.MODIFIED, "workspace", path, "note.md"
            ))
            self.assertEqual(metrics.snapshot(), {"events_received": 1, "documents_indexed": 1, "events_ignored": 1})


if __name__ == "__main__":
    unittest.main()
