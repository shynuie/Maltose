from __future__ import annotations

import unittest
from pathlib import Path

from maltose.knowledge.chunker import DocumentChunker
from maltose.knowledge.models import ParsedDocument, ParsedPage, ParsedSection


class KnowledgeChunkerTests(unittest.TestCase):
    def test_chunks_preserve_offsets_and_overlap(self) -> None:
        text = "0123456789abcdefghij"
        document = ParsedDocument(path=Path("sample.txt"), text=text, title="sample", file_type="txt")

        chunks = DocumentChunker(chunk_size=10, chunk_overlap=2).chunk(document)

        self.assertEqual([(chunk.start_offset, chunk.end_offset) for chunk in chunks], [(0, 10), (8, 18), (16, 20)])
        for chunk in chunks:
            self.assertEqual(text[chunk.start_offset : chunk.end_offset], chunk.text)

    def test_chunks_preserve_section_and_page_location(self) -> None:
        text = "intro\ndesign details"
        document = ParsedDocument(
            path=Path("sample.md"),
            text=text,
            title="Intro",
            file_type="markdown",
            pages=(ParsedPage(page=1, text=text, start_offset=0, end_offset=len(text)),),
            sections=(ParsedSection("Design", "design details", 6, len(text)),),
        )

        chunks = DocumentChunker(chunk_size=10, chunk_overlap=0).chunk(document)

        self.assertEqual(chunks[0].page, 1)
        self.assertIsNone(chunks[0].section)
        self.assertEqual(chunks[1].section, "Design")

    def test_empty_document_has_no_chunks(self) -> None:
        document = ParsedDocument(path=Path("empty.txt"), text="", title="empty", file_type="txt")
        self.assertEqual(DocumentChunker().chunk(document), [])

    def test_rejects_invalid_chunk_configuration(self) -> None:
        with self.assertRaises(ValueError):
            DocumentChunker(chunk_size=0)
        with self.assertRaises(ValueError):
            DocumentChunker(chunk_size=10, chunk_overlap=10)


if __name__ == "__main__":
    unittest.main()
