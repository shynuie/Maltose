from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from myagent.knowledge.curation import CuratedKnowledgeStore, KnowledgeProposalStore


class CuratedKnowledgeStoreTests(unittest.TestCase):
    class FakeEmbedder:
        def embed(self, text, *, is_query=False):
            return [1.0, 0.0] if "queue" in text.casefold() else [0.0, 1.0]

    def test_only_approved_proposals_can_be_published(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            proposals = KnowledgeProposalStore(Path(directory) / "proposals.json")
            curated = CuratedKnowledgeStore(Path(directory) / "curated.json")
            proposal = proposals.create(
                proposal_type="fact",
                content="The service uses a local queue.",
                sources=[{"root": "documents", "path": "architecture.md"}],
            )
            with self.assertRaises(ValueError):
                curated.publish(proposal, publisher="user")

            approved = proposals.approve(proposal.proposal_id, reviewer="user")
            entry = curated.publish(approved, publisher="user")

            self.assertEqual(entry.source_type, "agent_curated")
            self.assertEqual(entry.proposal_id, proposal.proposal_id)
            self.assertEqual(curated.list()[0].content, proposal.content)
            search = curated.search("local queue")
            self.assertEqual(search[0]["source_type"], "agent_curated")

    def test_duplicate_publish_and_revoke_are_safe(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            proposals = KnowledgeProposalStore(Path(directory) / "proposals.json")
            curated = CuratedKnowledgeStore(Path(directory) / "curated.json")
            proposal = proposals.create(proposal_type="observation", content="A note")
            approved = proposals.approve(proposal.proposal_id, reviewer="user")
            entry = curated.publish(approved, publisher="user")
            with self.assertRaises(ValueError):
                curated.publish(approved, publisher="user")
            revoked = curated.revoke(entry.curated_id, reviewer="user", reason="Outdated")

            self.assertEqual(revoked.status, "revoked")
            self.assertEqual(curated.list(), [])
            self.assertEqual(curated.list(active_only=False)[0].revocation_reason, "Outdated")
            with self.assertRaises(ValueError):
                curated.revoke(entry.curated_id, reviewer="user", reason="Again")

    def test_embedding_ranking_is_persisted_and_used_when_available(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            proposals = KnowledgeProposalStore(Path(directory) / "proposals.json")
            curated = CuratedKnowledgeStore(
                Path(directory) / "curated.json", embedder=self.FakeEmbedder()
            )
            first = proposals.create(proposal_type="observation", content="queue detail")
            second = proposals.create(proposal_type="observation", content="other detail")
            curated.publish(proposals.approve(first.proposal_id, reviewer="user"), publisher="user")
            curated.publish(proposals.approve(second.proposal_id, reviewer="user"), publisher="user")

            results = curated.search("queue", top_k=2, include_uncertain=True)

            self.assertEqual(results[0]["content"], "queue detail")
            self.assertEqual(results[0]["similarity_score"], 1.0)


if __name__ == "__main__":
    unittest.main()
