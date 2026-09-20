from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from myagent.knowledge.change_detection import DocumentChangeDetector
from myagent.knowledge.config import KnowledgeConfig
from myagent.knowledge.repositories import MetadataRepository
from myagent.knowledge.scanner import DocumentScanner


class KnowledgeChangeDetectionTests(unittest.TestCase):
    def test_unchanged_file_is_not_reindexed(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            path = root / "note.txt"
            path.write_text("same", encoding="utf-8")
            scanner = DocumentScanner((".txt",))
            with MetadataRepository(root / "metadata.sqlite3") as repository:
                scanned = scanner.scan(root).files[0]
                repository.upsert_scanned_file(scanned)
                plan = DocumentChangeDetector().plan(scanner.scan(root), repository)

            self.assertEqual(len(plan.new_files), 0)
            self.assertEqual(len(plan.changed_files), 0)
            self.assertEqual(len(plan.unchanged_files), 1)

    def test_same_content_at_new_path_is_a_move(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            old_path = root / "old.txt"
            old_path.write_text("same", encoding="utf-8")
            scanner = DocumentScanner((".txt",))
            with MetadataRepository(root / "metadata.sqlite3") as repository:
                old_file = scanner.scan(root).files[0]
                document_id = repository.upsert_scanned_file(old_file)
                new_path = root / "new.txt"
                old_path.rename(new_path)
                plan = DocumentChangeDetector().plan(scanner.scan(root), repository)
                stored = repository.get_by_id(document_id)

            self.assertEqual(plan.moved_document_ids, (document_id,))
            self.assertEqual(stored["path"], str(new_path.resolve()))

    def test_missing_file_is_marked_deleted(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            path = root / "gone.txt"
            path.write_text("gone", encoding="utf-8")
            scanner = DocumentScanner((".txt",))
            with MetadataRepository(root / "metadata.sqlite3") as repository:
                scanned = scanner.scan(root).files[0]
                document_id = repository.upsert_scanned_file(scanned)
                path.unlink()
                plan = DocumentChangeDetector().plan(scanner.scan(root), repository)
                stored = repository.get_by_id(document_id)

            self.assertEqual(plan.deleted_document_ids, (document_id,))
            self.assertEqual(stored["status"], "deleted")

    def test_config_resolves_relative_paths_without_hardcoding_root(self) -> None:
        base = Path("/tmp/myagent").resolve()
        config = KnowledgeConfig().resolved(base_dir=base)
        self.assertEqual(config.documents_root, base / "documents")
        self.assertEqual(config.metadata_path, base / "data/knowledge/metadata.sqlite3")


if __name__ == "__main__":
    unittest.main()
