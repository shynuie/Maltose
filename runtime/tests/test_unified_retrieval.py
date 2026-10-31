from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from myagent.knowledge.curation import CuratedKnowledgeStore, KnowledgeProposalStore
from myagent.knowledge.models import ScannedFile
from myagent.knowledge.repositories import MetadataRepository
from myagent.knowledge.retrieval import DocumentKnowledgeService
from myagent.knowledge.scanner import DocumentScanner
from myagent.knowledge.source_reader import SourceReader
from myagent.knowledge.parsers import ParserRegistry, TextParser
from myagent.knowledge.unified_retrieval import UnifiedKnowledgeService


class FakeEmbedder:
    def embed(self, text):
        return [1.0]


class FakeVectors:
    def __init__(self, document_id: str):
        self.document_id = document_id

    def search_summaries(self, embedding, limit):
        return [{"document_id": self.document_id, "similarity_score": 0.5}][:limit]

    def search_chunks(self, document_ids, embedding, limit):
        return []


class UnifiedRetrievalTests(unittest.TestCase):
    def test_truth_results_are_labeled_and_precede_curated_results(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            document = root / "truth.txt"
            document.write_text("truth", encoding="utf-8")
            scanned = DocumentScanner((".txt",)).scan(root).files[0]
            metadata = MetadataRepository(root / "metadata.sqlite3")
            document_id = metadata.upsert_scanned_file(scanned, status="indexed")
            metadata.mark_indexed(document_id, title="Truth", summary="Truth summary")
            truth = DocumentKnowledgeService(
                metadata=metadata,
                vectors=FakeVectors(document_id),
                embedder=FakeEmbedder(),
                source_reader=SourceReader(
                    metadata=metadata,
                    documents_root=root,
                    parsers=ParserRegistry([TextParser()]),
                ),
            )
            proposals = KnowledgeProposalStore(root / "proposals.json")
            proposal = proposals.create(
                proposal_type="fact",
                content="curated note",
                sources=[{"root": "documents", "path": "truth.txt"}],
            )
            curated_store = CuratedKnowledgeStore(root / "curated.json")
            curated_store.publish(proposals.approve(proposal.proposal_id, reviewer="user"), publisher="user")

            results = UnifiedKnowledgeService(truth=truth, curated=curated_store).search("truth note")

            self.assertEqual(results[0]["source_type"], "truth")
            self.assertEqual(results[1]["source_type"], "agent_curated")
            metadata.close()


if __name__ == "__main__":
    unittest.main()
