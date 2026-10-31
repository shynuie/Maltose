from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from myagent.knowledge.parsers import MarkdownParser, ParserRegistry, TextParser
from myagent.knowledge.repositories import MetadataRepository
from myagent.knowledge.retrieval import DocumentKnowledgeService
from myagent.knowledge.scanner import DocumentScanner
from myagent.knowledge.source_reader import SourceReader
from myagent.knowledge.tools import DocumentToolAdapter


class FakeEmbedder:
    def embed(self, text):
        return [float(len(text))]


class FakeVectors:
    def __init__(self, document_id):
        self.document_id = document_id

    def search_summaries(self, embedding, limit):
        return [{"document_id": self.document_id, "similarity_score": 0.9}]

    def search_chunks(self, document_ids, embedding, limit):
        return [{
            "id": "chunk-1",
            "document_id": document_ids[0],
            "page": None,
            "section": "Design",
            "start_offset": 0,
            "end_offset": 5,
            "similarity_score": 0.8,
            "text_preview": "hello",
        }]


class KnowledgeToolsTests(unittest.TestCase):
    def test_adapter_exposes_three_tools_and_reads_source(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            path = root / "note.txt"
            path.write_text("hello", encoding="utf-8")
            scanned = DocumentScanner((".txt",)).scan(root).files[0]
            with MetadataRepository(root / "metadata.sqlite3") as metadata:
                document_id = metadata.upsert_scanned_file(scanned, status="indexed")
                service = DocumentKnowledgeService(
                    metadata=metadata,
                    vectors=FakeVectors(document_id),
                    embedder=FakeEmbedder(),
                    source_reader=SourceReader(
                        metadata=metadata,
                        documents_root=root,
                        parsers=ParserRegistry([TextParser(), MarkdownParser()]),
                    ),
                )
                adapter = DocumentToolAdapter(service)
                tools = {tool.name: tool for tool in adapter.tools()}
                source = tools["read_document"].handler({"document_id": document_id})

            self.assertEqual(set(tools), {"search_documents", "search_in_document", "read_document"})
            self.assertEqual(source["text"], "hello")


if __name__ == "__main__":
    unittest.main()
