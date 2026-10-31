from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from myagent.knowledge.curation import CuratedKnowledgeStore, KnowledgeProposalStore, KnowledgeSourcePolicy
from myagent.knowledge.curation_tools import KnowledgeCurationToolAdapter
from myagent.knowledge.curation_ui import KnowledgeProposalUI


class KnowledgeCurationToolsTests(unittest.TestCase):
    def test_source_policy_rejects_development_root_and_accepts_truth_file(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            base = Path(directory)
            documents = base / "documents"
            documents.mkdir()
            (documents / "guide.md").write_text("guide", encoding="utf-8")
            store = KnowledgeProposalStore(
                base / "proposals.json",
                source_policy=KnowledgeSourcePolicy({"documents": documents}),
            )
            proposal = store.create(
                proposal_type="fact", content="A sourced fact.",
                sources=[{"root": "documents", "path": "guide.md"}],
            )
            self.assertEqual(proposal.status, "pending")
            with self.assertRaises(PermissionError):
                store.create(
                    proposal_type="fact", content="A development fact.",
                    sources=[{"root": "dev", "path": "plan.md"}],
                )

    def test_agent_adapter_only_exposes_propose_and_list(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            store = KnowledgeProposalStore(Path(directory) / "proposals.json")
            tools = KnowledgeCurationToolAdapter(store).tools()
            self.assertEqual(
                {tool.name for tool in tools},
                {"propose_knowledge", "list_knowledge_proposals", "search_curated_knowledge"},
            )

    def test_ui_approval_is_user_scoped_and_publishes_terminal_state(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            store = KnowledgeProposalStore(Path(directory) / "proposals.json")
            events: list[tuple[str, dict[str, object]]] = []
            ui = KnowledgeProposalUI(store, reviewer="user", publisher=lambda t, p: events.append((t, p)))
            proposal = store.create(proposal_type="observation", content="Maybe true")
            ui.publish_request(proposal)
            approved = ui.handle_action("knowledge.approve", {"proposal_id": proposal.proposal_id})
            self.assertEqual(approved.status, "approved")
            self.assertEqual(events[-1][1]["status"], "approved")
            rejected = store.create(proposal_type="observation", content="Definitely not")
            with self.assertRaises(ValueError):
                ui.handle_action("knowledge.reject", {"proposal_id": rejected.proposal_id})


if __name__ == "__main__":
    unittest.main()
