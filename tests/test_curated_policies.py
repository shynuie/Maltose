from __future__ import annotations

import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path

from myagent.knowledge.curation import CuratedKnowledgeStore, KnowledgeProposal, KnowledgeProposalStore


class CuratedPolicyTests(unittest.TestCase):
    def test_active_duplicate_content_is_rejected_until_old_entry_is_revoked(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            proposals = KnowledgeProposalStore(Path(directory) / "proposals.json")
            curated = CuratedKnowledgeStore(Path(directory) / "curated.json")
            first = proposals.create(proposal_type="fact", content="Use uv.", sources=[{"root": "documents", "path": "a.md"}])
            first_entry = curated.publish(proposals.approve(first.proposal_id, reviewer="user"), publisher="user")
            second = KnowledgeProposal(
                proposal_id="second",
                type="fact",
                content="  use   UV. ",
                sources=({"root": "documents", "path": "b.md"},),
                confidence=0.5,
                created_by="agent",
                status="approved",
                created_at=datetime.now(timezone.utc).isoformat(),
            )
            with self.assertRaises(ValueError):
                curated.publish(second, publisher="user")
            curated.revoke(first_entry.curated_id, reviewer="user", reason="Superseded")
            curated.publish(second, publisher="user")

    def test_stale_entries_are_excluded_and_repair_reports_them(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            proposals = KnowledgeProposalStore(Path(directory) / "proposals.json")
            curated = CuratedKnowledgeStore(Path(directory) / "curated.json", stale_after_days=1)
            proposal = proposals.create(proposal_type="observation", content="Old note")
            entry = curated.publish(proposals.approve(proposal.proposal_id, reviewer="user"), publisher="user")
            old = entry.__class__(**{
                **entry.__dict__,
                "published_at": (datetime.now(timezone.utc) - timedelta(days=2)).isoformat(),
            })
            curated._save([old])

            self.assertEqual(curated.list(), [])
            self.assertEqual(curated.repair()["stale"], 1)

    def test_uncertain_entries_are_hidden_unless_explicitly_requested(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            proposals = KnowledgeProposalStore(Path(directory) / "proposals.json")
            curated_path = Path(directory) / "curated.json"
            curated = CuratedKnowledgeStore(curated_path)
            proposal = proposals.create(proposal_type="observation", content="Maybe queue")
            approved = proposals.approve(proposal.proposal_id, reviewer="user")
            curated.publish(approved, publisher="user")

            self.assertEqual(curated.search("queue"), [])
            self.assertEqual(len(curated.search("queue", include_uncertain=True)), 1)

    def test_store_can_restart_and_report_orphaned_active_entries(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            proposals = KnowledgeProposalStore(Path(directory) / "proposals.json")
            curated_path = Path(directory) / "curated.json"
            curated = CuratedKnowledgeStore(curated_path)
            proposal = proposals.create(proposal_type="observation", content="Persisted note")
            entry = curated.publish(proposals.approve(proposal.proposal_id, reviewer="user"), publisher="user")
            restarted = CuratedKnowledgeStore(curated_path)
            self.assertEqual(restarted.list(active_only=False)[0].curated_id, entry.curated_id)
            orphan = entry.__class__(**{**entry.__dict__, "proposal_id": "missing"})
            restarted._save([orphan])
            self.assertEqual(restarted.repair(proposals=proposals)["orphaned"], 1)


if __name__ == "__main__":
    unittest.main()
