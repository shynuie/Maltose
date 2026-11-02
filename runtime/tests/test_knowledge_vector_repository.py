from __future__ import annotations

import unittest
import tempfile
from pathlib import Path

from maltose.knowledge.models import DocumentChunk
from maltose.knowledge.repositories.lancedb import LanceVectorRepository


class KnowledgeVectorRepositoryTests(unittest.TestCase):
    def test_chunk_rows_keep_source_location(self) -> None:
        chunk = DocumentChunk(
            chunk_index=3,
            text="source preview",
            start_offset=120,
            end_offset=134,
            page=4,
            section="Methods",
            metadata={"source_path": "documents/paper.pdf"},
        )

        row = LanceVectorRepository._chunk_row("doc_1", chunk, [0.1, 0.2])

        self.assertEqual(row["document_id"], "doc_1")
        self.assertEqual(row["page"], 4)
        self.assertEqual(row["section"], "Methods")
        self.assertEqual(row["start_offset"], 120)
        self.assertEqual(row["end_offset"], 134)
        self.assertEqual(row["embedding"], [0.1, 0.2])

    def test_default_path_is_separate_from_memory_store(self) -> None:
        self.assertEqual(
            Path("data/knowledge/vectors.lancedb"),
            Path("data/knowledge/vectors.lancedb"),
        )
        self.assertNotEqual(
            Path("data/knowledge/vectors.lancedb"),
            Path("data/memory/memory.lancedb"),
        )

    def test_nullable_section_schema_migrates_when_later_chunk_has_heading(self) -> None:
        try:
            import lancedb  # noqa: F401
        except ImportError:
            self.skipTest("lancedb is not installed")

        with tempfile.TemporaryDirectory() as directory:
            repository = LanceVectorRepository(Path(directory) / "vectors.lancedb")
            repository.replace_document(
                "doc-1",
                summary="first",
                summary_embedding=[0.1, 0.2],
                chunks=[(
                    DocumentChunk(0, "first", 0, 5, section=None),
                    [0.1, 0.2],
                )],
            )
            repository.replace_document(
                "doc-2",
                summary="second",
                summary_embedding=[0.2, 0.3],
                chunks=[(
                    DocumentChunk(0, "second", 0, 6, section="Design"),
                    [0.2, 0.3],
                )],
            )

            table = repository._db.open_table(repository.chunk_table_name)
            self.assertEqual(str(table.schema.field("section").type), "string")
            rows = table.to_arrow().to_pylist()
            self.assertEqual(
                {row["section"] for row in rows},
                {None, "Design"},
            )


if __name__ == "__main__":
    unittest.main()
