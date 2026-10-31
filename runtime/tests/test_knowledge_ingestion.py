from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from maltose.knowledge.indexer import IndexResult
from maltose.knowledge.ingestion import DocumentIngestionService
from maltose.knowledge.scanner import DocumentScanner


class FakeIndexer:
    def index(self, scanned):
        return IndexResult("doc-test", 1, "indexed")


class KnowledgeIngestionTests(unittest.TestCase):
    def test_create_document_writes_inside_root_and_indexes_it(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory) / "documents"
            service = DocumentIngestionService(
                documents_root=root,
                scanner=DocumentScanner((".md", ".txt")),
                indexer=FakeIndexer(),
            )

            result = service.create_document(
                content="# Meeting\nNotes",
                filename="meeting.md",
            )

            self.assertEqual(result.path, (root / "inbox/meeting.md").resolve())
            self.assertEqual(result.index.status, "indexed")
            self.assertEqual(result.path.read_text(encoding="utf-8"), "# Meeting\nNotes")

    def test_import_rejects_destination_escape(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory) / "documents"
            source = Path(directory) / "source.txt"
            source.write_text("secret", encoding="utf-8")
            service = DocumentIngestionService(
                documents_root=root,
                scanner=DocumentScanner((".txt",)),
                indexer=FakeIndexer(),
            )

            with self.assertRaises(PermissionError):
                service.import_file(source, "../outside.txt")


if __name__ == "__main__":
    unittest.main()
