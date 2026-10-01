"""User review bridge for knowledge proposal approval."""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

from myagent.knowledge.curation import CuratedKnowledgeStore, KnowledgeProposal, KnowledgeProposalStore


class KnowledgeProposalUI:
    def __init__(
        self,
        store: KnowledgeProposalStore,
        *,
        reviewer: str,
        publisher: Callable[[str, dict[str, Any]], Any],
        curated_store: CuratedKnowledgeStore | None = None,
        truth_checker: Callable[[str], list[Any]] | None = None,
    ) -> None:
        self.store = store
        self.reviewer = reviewer
        self.publisher = publisher
        self.curated_store = curated_store
        self.truth_checker = truth_checker

    def set_truth_checker(self, checker: Callable[[str], list[Any]] | None) -> None:
        self.truth_checker = checker

    def publish_request(self, proposal: KnowledgeProposal) -> None:
        self.publisher("ui_confirmation", {
            "block_id": f"knowledge-proposal-{proposal.proposal_id}",
            "proposal_id": proposal.proposal_id,
            "title": "Knowledge proposal review",
            "content": proposal.content,
            "status": "pending",
            "actions": [
                {"id": "knowledge.approve", "label": "Approve"},
                {"id": "knowledge.reject", "label": "Reject"},
            ],
            "value": {"proposal_id": proposal.proposal_id},
        })

    def handle_action(self, action_id: str, value: object) -> KnowledgeProposal:
        if not isinstance(value, dict) or not isinstance(value.get("proposal_id"), str):
            raise ValueError("Knowledge action requires proposal_id.")
        proposal_id = value["proposal_id"]
        if action_id == "knowledge.approve":
            pending = self.store.get(proposal_id)
            if self.curated_store is not None:
                conflicts = self.curated_store.find_potential_conflicts(
                    pending.content,
                    proposal_type=pending.type,
                )
                if conflicts:
                    self.publisher("ui_confirmation", {
                        "block_id": f"knowledge-proposal-{proposal_id}",
                        "proposal_id": proposal_id,
                        "title": "Knowledge proposal needs conflict review",
                        "content": "A similar curated knowledge entry already exists. Revoke or revise it before approving.",
                        "status": "conflict",
                        "actions": [],
                        "value": {"proposal_id": proposal_id},
                    })
                    raise ValueError("Knowledge proposal requires conflict review.")
            if self.truth_checker is not None:
                truth_matches = self.truth_checker(pending.content)
                strong_matches = []
                for item in truth_matches:
                    score = item.get("similarity_score", 0) if isinstance(item, dict) else getattr(item, "similarity_score", 0)
                    if float(score or 0) >= 0.85:
                        strong_matches.append(item)
                if strong_matches:
                    self.publisher("ui_confirmation", {
                        "block_id": f"knowledge-proposal-{proposal_id}",
                        "proposal_id": proposal_id,
                        "title": "Knowledge proposal needs truth review",
                        "content": "A truth document appears highly relevant. Verify the proposal against the original source before approving.",
                        "status": "truth_conflict",
                        "actions": [],
                        "value": {"proposal_id": proposal_id},
                    })
                    raise ValueError("Knowledge proposal requires truth review.")
            proposal = self.store.approve(proposal_id, reviewer=self.reviewer)
            if self.curated_store is not None:
                self.curated_store.publish(proposal, publisher=self.reviewer)
                status, content = "published", "Approved and published to curated knowledge."
            else:
                status, content = "approved", "Approved. It can be published to curated knowledge in a later step."
        elif action_id == "knowledge.reject":
            reason = value.get("reason")
            if not isinstance(reason, str) or not reason.strip():
                raise ValueError("Rejecting a proposal requires a reason.")
            proposal = self.store.reject(proposal_id, reviewer=self.reviewer, reason=reason)
            status, content = "rejected", f"Rejected: {reason.strip()}"
        else:
            raise ValueError(f"Unknown knowledge action: {action_id}")
        self.publisher("ui_confirmation", {
            "block_id": f"knowledge-proposal-{proposal.proposal_id}",
            "proposal_id": proposal.proposal_id,
            "title": "Knowledge proposal review",
            "content": content,
            "status": status,
            "actions": [],
            "value": {"proposal_id": proposal.proposal_id},
        })
        return proposal
