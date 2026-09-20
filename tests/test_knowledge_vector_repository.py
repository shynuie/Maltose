from __future__ import annotations

import unittest
from pathlib import Path

from myagent.knowledge.models import DocumentChunk
from myagent.knowledge.repositories.lancedb import LanceVectorRepository


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
            Path("data/memory.lancedb"),
        )


if __name__ == "__main__":
    unittest.main()
