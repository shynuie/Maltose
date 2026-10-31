from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from myagent.knowledge.embeddings import EmbeddingProvider
from myagent.knowledge.models import DocumentLocation
from myagent.knowledge.parsers import MarkdownParser, ParserRegistry, TextParser
from myagent.knowledge.repositories import MetadataRepository
from myagent.knowledge.retrieval import DocumentKnowledgeService
from myagent.knowledge.scanner import DocumentScanner
from myagent.knowledge.source_reader import SourceReader


class FakeEmbedder:
    def embed(self, text):
        return [float(len(text))]


class FakeVectors:
    def __init__(self, document_id="doc-1"):
        self.document_id = document_id

    def search_summaries(self, embedding, limit):
        return [{"document_id": self.document_id, "similarity_score": 0.9}][:limit]

    def search_chunks(self, document_ids, embedding, limit):
        return [{
            "id": "chunk-1",
            "document_id": document_ids[0],
            "page": None,
            "section": "Design",
            "start_offset": 7,
            "end_offset": 19,
            "similarity_score": 0.8,
            "text_preview": "design details",
        }][:limit]


class KnowledgeRetrievalTests(unittest.TestCase):
    def _service(self, root, metadata, document_id="doc-1"):
        return DocumentKnowledgeService(
            metadata=metadata,
            vectors=FakeVectors(document_id),
            embedder=FakeEmbedder(),
            source_reader=SourceReader(
                metadata=metadata,
                documents_root=root,
                parsers=ParserRegistry([TextParser(), MarkdownParser()]),
            ),
        )

    def test_hierarchical_retrieval_returns_document_then_chunk(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            path = root / "plan.md"
            path.write_text("# Overview\nintro\n\n## Design\ndesign details", encoding="utf-8")
            scanned = DocumentScanner((".md",)).scan(root).files[0]
            with MetadataRepository(root / "metadata.sqlite3") as metadata:
                document_id = metadata.upsert_scanned_file(scanned, title="Plan", status="indexed")
                metadata.mark_indexed(document_id, title="Plan", summary="A plan")
                service = self._service(root, metadata, document_id)
                documents = service.search_documents("design")
                chunks = service.search_in_document(document_id, "design")

            self.assertEqual(documents[0].document_id, document_id)
            self.assertEqual(chunks[0].section, "Design")

    def test_source_reader_reads_section_and_offsets(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            path = root / "plan.md"
            content = "# Overview\nintro\n\n## Design\ndesign details"
            path.write_text(content, encoding="utf-8")
            scanned = DocumentScanner((".md",)).scan(root).files[0]
            with MetadataRepository(root / "metadata.sqlite3") as metadata:
                document_id = metadata.upsert_scanned_file(scanned, status="indexed")
                reader = SourceReader(
                    metadata=metadata,
                    documents_root=root,
                    parsers=ParserRegistry([TextParser(), MarkdownParser()]),
                )
                section = reader.read(document_id, DocumentLocation(section="Design"))
                offset = reader.read(document_id, DocumentLocation(start_offset=0, end_offset=10))

            self.assertTrue(section.text.startswith("## Design"))
            self.assertEqual(offset.text, content[:10])

    def test_source_reader_rejects_path_outside_root(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory) / "documents"
            root.mkdir()
            outside = Path(directory) / "outside.txt"
            outside.write_text("secret", encoding="utf-8")
            with MetadataRepository(Path(directory) / "metadata.sqlite3") as metadata:
                document_id = metadata.upsert_scanned_file(
                    DocumentScanner((".txt",)).scan(outside.parent).files[0], status="indexed"
                )
                reader = SourceReader(
                    metadata=metadata,
                    documents_root=root,
                    parsers=ParserRegistry([TextParser()]),
                )
                with self.assertRaises(PermissionError):
                    reader.read(document_id)


if __name__ == "__main__":
    unittest.main()
