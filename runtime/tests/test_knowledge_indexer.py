from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from maltose.knowledge.chunker import DocumentChunker
from maltose.knowledge.indexer import DocumentIndexer
from maltose.knowledge.parsers import MarkdownParser, ParserRegistry, TextParser
from maltose.knowledge.repositories import MetadataRepository
from maltose.knowledge.scanner import DocumentScanner


class FakeSummarizer:
    def summarize(self, document):
        return f"Summary of {document.title}"


class FakeEmbedder:
    def embed(self, text):
        return [float(len(text)), 1.0]


class FakeVectorRepository:
    def __init__(self):
        self.documents = {}

    def replace_document(self, document_id, *, summary, summary_embedding, chunks):
        self.documents[document_id] = {
            "summary": summary,
            "summary_embedding": summary_embedding,
            "chunks": chunks,
        }


class FailingVectorRepository(FakeVectorRepository):
    def replace_document(self, *args, **kwargs):
        raise RuntimeError("vector write failed")


class KnowledgeIndexerTests(unittest.TestCase):
    def _indexer(self, metadata, vectors):
        return DocumentIndexer(
            parsers=ParserRegistry([TextParser(), MarkdownParser()]),
            chunker=DocumentChunker(chunk_size=8, chunk_overlap=2),
            summarizer=FakeSummarizer(),
            embedder=FakeEmbedder(),
            metadata=metadata,
            vectors=vectors,
        )

    def test_indexer_runs_parse_summary_chunk_embed_and_persist(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            path = root / "note.txt"
            path.write_text("hello knowledge base", encoding="utf-8")
            scanned = DocumentScanner((".txt",)).scan(root).files[0]
            vectors = FakeVectorRepository()
            with MetadataRepository(root / "metadata.sqlite3") as metadata:
                result = self._indexer(metadata, vectors).index(scanned)
                stored = metadata.get_by_id(result.document_id)

            self.assertEqual(result.status, "indexed")
            self.assertGreater(result.chunk_count, 1)
            self.assertEqual(stored["status"], "indexed")
            self.assertEqual(vectors.documents[result.document_id]["summary"], "Summary of note")

    def test_failed_vector_write_marks_document_failed(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            path = root / "note.txt"
            path.write_text("hello", encoding="utf-8")
            scanned = DocumentScanner((".txt",)).scan(root).files[0]
            with MetadataRepository(root / "metadata.sqlite3") as metadata:
                with self.assertRaisesRegex(RuntimeError, "vector write failed"):
                    self._indexer(metadata, FailingVectorRepository()).index(scanned)
                stored = metadata.get_by_path(path.resolve())

            self.assertEqual(stored["status"], "indexing_failed")


if __name__ == "__main__":
    unittest.main()
