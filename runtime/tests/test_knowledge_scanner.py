from __future__ import annotations

import tempfile
import unittest
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

from maltose.knowledge.repositories import MetadataRepository
from maltose.knowledge.scanner import DocumentScanner


class KnowledgeScannerTests(unittest.TestCase):
    def test_scanner_filters_extensions_and_calculates_hash(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            document = root / "work" / "report.txt"
            document.parent.mkdir()
            document.write_text("hello", encoding="utf-8")
            (root / "ignored.py").write_text("pass", encoding="utf-8")

            result = DocumentScanner((".txt",)).scan(root)

            self.assertEqual(len(result.files), 1)
            self.assertEqual(result.files[0].relative_path, "work/report.txt")
            self.assertEqual(len(result.files[0].content_hash), 64)

    def test_metadata_repository_preserves_document_id_for_same_path(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            document = root / "note.txt"
            document.write_text("one", encoding="utf-8")
            scanner = DocumentScanner((".txt",))
            scanned = scanner.scan(root).files[0]

            with MetadataRepository(root / "metadata.sqlite3") as repository:
                first_id = repository.upsert_scanned_file(scanned, collection="notes")
                second_id = repository.upsert_scanned_file(scanned, collection="notes")
                stored = repository.get_by_id(first_id)

            self.assertEqual(first_id, second_id)
            self.assertEqual(stored["status"], "pending_index")
            self.assertEqual(stored["collection"], "notes")

    def test_metadata_repository_can_be_read_from_worker_thread(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            document = root / "note.txt"
            document.write_text("thread safe", encoding="utf-8")
            scanned = DocumentScanner((".txt",)).scan(root).files[0]

            with MetadataRepository(root / "metadata.sqlite3") as repository:
                document_id = repository.upsert_scanned_file(scanned)
                with ThreadPoolExecutor(max_workers=1) as executor:
                    stored = executor.submit(repository.get_by_id, document_id).result()

            self.assertEqual(stored["id"], document_id)


if __name__ == "__main__":
    unittest.main()
