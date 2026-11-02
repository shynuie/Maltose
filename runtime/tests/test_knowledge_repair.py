from __future__ import annotations

import tempfile
import unittest
from datetime import datetime, timezone
from pathlib import Path

from maltose.knowledge.models import ScannedFile
from maltose.knowledge.repair import find_orphan_vector_ids, find_repair_candidates
from maltose.knowledge.repositories.metadata import MetadataRepository
from maltose.knowledge.scanner import DocumentScanner


class KnowledgeRepairTests(unittest.TestCase):
    def test_finds_failed_and_pending_source_files(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            failed = root / "failed.txt"
            pending = root / "pending.txt"
            indexed = root / "indexed.txt"
            for path in (failed, pending, indexed):
                path.write_text(path.stem, encoding="utf-8")
            scanner = DocumentScanner()
            scan = scanner.scan(root)
            metadata = MetadataRepository(root / "metadata.sqlite3")
            files = {item.path.name: item for item in scan.files}
            metadata.upsert_scanned_file(files["failed.txt"], status="indexing_failed")
            metadata.upsert_scanned_file(files["pending.txt"], status="pending_index")
            metadata.upsert_scanned_file(files["indexed.txt"], status="indexed")

            candidates = find_repair_candidates(scan, metadata)

            self.assertEqual({item.path.name for item in candidates}, {"failed.txt", "pending.txt"})
            metadata.close()

    def test_force_returns_all_scanned_files(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            path = root / "note.txt"
            path.write_text("note", encoding="utf-8")
            metadata = MetadataRepository(root / "metadata.sqlite3")
            scan = DocumentScanner().scan(root)

            self.assertEqual(find_repair_candidates(scan, metadata, force=True), scan.files)
            metadata.close()

    def test_finds_missing_and_deleted_metadata_for_vectors(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            metadata = MetadataRepository(Path(directory) / "metadata.sqlite3")
            active = metadata.upsert_scanned_file(
                ScannedFile(
                    path=Path(directory) / "active.txt",
                    relative_path="active.txt",
                    filename="active.txt",
                    file_type="txt",
                    content_hash="active",
                    file_size=1,
                    modified_at=datetime.now(timezone.utc),
                ),
                status="indexed",
            )
            deleted = metadata.upsert_scanned_file(
                ScannedFile(
                    path=Path(directory) / "deleted.txt",
                    relative_path="deleted.txt",
                    filename="deleted.txt",
                    file_type="txt",
                    content_hash="deleted",
                    file_size=1,
                    modified_at=datetime.now(timezone.utc),
                ),
                status="deleted",
            )

            class Vectors:
                def list_document_ids(self) -> set[str]:
                    return {active, deleted, "missing"}

            self.assertEqual(find_orphan_vector_ids(metadata, Vectors()), (deleted, "missing"))
            metadata.close()


if __name__ == "__main__":
    unittest.main()
