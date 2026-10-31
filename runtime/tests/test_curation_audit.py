from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from maltose.knowledge.curation import CurationAuditLog, CuratedKnowledgeStore, KnowledgeProposalStore


class CurationAuditTests(unittest.TestCase):
    def test_audit_events_persist_and_similar_publish_is_blocked(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            base = Path(directory)
            audit = CurationAuditLog(base / "audit.jsonl")
            proposals = KnowledgeProposalStore(base / "proposals.json", audit_log=audit)
            curated = CuratedKnowledgeStore(base / "curated.json", audit_log=audit)
            first = proposals.create(
                proposal_type="fact", content="Use uv",
                sources=[{"root": "documents", "path": "a.md"}],
            )
            curated.publish(proposals.approve(first.proposal_id, reviewer="user"), publisher="user")
            second = proposals.create(
                proposal_type="fact", content="Use uv now",
                sources=[{"root": "documents", "path": "b.md"}],
            )
            with self.assertRaises(ValueError):
                curated.publish(proposals.approve(second.proposal_id, reviewer="user"), publisher="user")
            events = [json.loads(line) for line in (base / "audit.jsonl").read_text().splitlines()]
            self.assertIn("proposal_created", {event["event"] for event in events})
            self.assertIn("curated_published", {event["event"] for event in events})


if __name__ == "__main__":
    unittest.main()
