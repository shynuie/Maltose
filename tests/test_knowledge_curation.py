from __future__ import annotations

import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path

from myagent.knowledge.curation import KnowledgeProposalStore, KnowledgeQualityPolicy


class KnowledgeCurationTests(unittest.TestCase):
    def make_store(self, directory: str) -> KnowledgeProposalStore:
        return KnowledgeProposalStore(Path(directory) / "proposals.json")

    def test_creates_persisted_pending_proposal_with_provenance(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            store = self.make_store(directory)
            proposal = store.create(
                proposal_type="fact",
                content="The project uses uv for commands.",
                sources=[{"root": "documents", "path": "guide.md"}],
                confidence=0.9,
            )

            loaded = self.make_store(directory).list(status="pending")

            self.assertEqual(loaded[0].proposal_id, proposal.proposal_id)
            self.assertEqual(loaded[0].sources[0]["root"], "documents")

    def test_rejects_unsourced_fact_and_duplicate_content(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            store = self.make_store(directory)
            with self.assertRaises(ValueError):
                store.create(proposal_type="fact", content="No source")
            store.create(
                proposal_type="summary",
                content="Same summary",
                sources=[{"root": "documents", "path": "a.md"}],
            )
            with self.assertRaises(ValueError):
                store.create(
                    proposal_type="summary",
                    content=" same   summary ",
                    sources=[{"root": "documents", "path": "b.md"}],
                )

    def test_approval_rejection_and_invalid_second_transition(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            store = self.make_store(directory)
            proposal = store.create(
                proposal_type="procedure",
                content="Run the tests with Python.",
                sources=[{"root": "documents", "path": "dev.md"}],
            )
            approved = store.approve(proposal.proposal_id, reviewer="user")
            self.assertTrue(store.policy.can_publish(approved))
            with self.assertRaises(ValueError):
                store.reject(proposal.proposal_id, reviewer="user", reason="Too late")

    def test_rejection_requires_reason_and_expired_proposal_cannot_be_approved(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            store = self.make_store(directory)
            proposal = store.create(
                proposal_type="observation",
                content="The watcher was restarted.",
                expires_at=(datetime.now(timezone.utc) - timedelta(seconds=1)).isoformat(),
            )
            self.assertEqual(store.list()[0].status, "expired")
            with self.assertRaises(ValueError):
                store.approve(proposal.proposal_id, reviewer="user")
            fresh = store.create(proposal_type="observation", content="Another observation")
            with self.assertRaises(ValueError):
                store.reject(fresh.proposal_id, reviewer="user", reason="")

    def test_quality_policy_limits_content_and_confidence(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            store = KnowledgeProposalStore(
                Path(directory) / "proposals.json",
                KnowledgeQualityPolicy(max_content_chars=5),
            )
            with self.assertRaises(ValueError):
                store.create(proposal_type="observation", content="too long")
            with self.assertRaises(ValueError):
                store.create(proposal_type="observation", content="ok", confidence=1.1)


if __name__ == "__main__":
    unittest.main()
