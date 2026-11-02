"""Agent-facing proposal tools; approval remains a user/UI action."""

from __future__ import annotations

from typing import Any, Callable

from maltose.agent.capabilities import CapabilityTool
from maltose.knowledge.curation import CuratedKnowledgeStore, KnowledgeProposalStore


class KnowledgeCurationToolAdapter:
    def __init__(
        self,
        store: KnowledgeProposalStore,
        *,
        proposal_notifier: Callable[[Any], Any] | None = None,
        curated_store: CuratedKnowledgeStore | None = None,
    ) -> None:
        self.store = store
        self.proposal_notifier = proposal_notifier
        self.curated_store = curated_store

    def tools(self) -> list[CapabilityTool]:
        return [
            CapabilityTool(
                name="propose_knowledge",
                description="Submit candidate knowledge for review; this does not write truth documents or KDB.",
                parameters={
                    "type": "object",
                    "properties": {
                        "type": {"type": "string"},
                        "content": {"type": "string"},
                        "sources": {"type": "array", "items": {"type": "object"}},
                        "confidence": {"type": "number", "minimum": 0, "maximum": 1},
                        "expires_at": {"type": "string"},
                    },
                    "required": ["type", "content"],
                },
                handler=self._propose,
            ),
            CapabilityTool(
                name="list_knowledge_proposals",
                description="List candidate knowledge proposals and their review status.",
                parameters={"type": "object", "properties": {"status": {"type": "string"}}},
                handler=self._list,
            ),
            CapabilityTool(
                name="search_curated_knowledge",
                description="Search user-approved Agent knowledge; results are labeled agent_curated and are not truth documents.",
                parameters={
                    "type": "object",
                    "properties": {
                        "query": {"type": "string"},
                        "top_k": {"type": "integer", "minimum": 1, "maximum": 20},
                        "include_uncertain": {"type": "boolean", "default": False},
                    },
                    "required": ["query"],
                },
                handler=self._search_curated,
            ),
        ]

    def _propose(self, arguments: dict[str, Any]) -> dict[str, Any]:
        proposal = self.store.create(
            proposal_type=arguments["type"],
            content=arguments["content"],
            sources=arguments.get("sources", []),
            confidence=float(arguments.get("confidence", 0.5)),
            expires_at=arguments.get("expires_at"),
        )
        if self.proposal_notifier is not None:
            self.proposal_notifier(proposal)
        return self._as_dict(proposal)

    def _list(self, arguments: dict[str, Any]) -> list[dict[str, Any]]:
        return [self._as_dict(item) for item in self.store.list(status=arguments.get("status"))]

    def _search_curated(self, arguments: dict[str, Any]) -> list[dict[str, Any]]:
        if self.curated_store is None:
            raise RuntimeError("Curated knowledge search is not enabled.")
        return self.curated_store.search(
            arguments["query"],
            top_k=int(arguments.get("top_k", 5)),
            include_uncertain=bool(arguments.get("include_uncertain", False)),
        )

    @staticmethod
    def _as_dict(value: Any) -> dict[str, Any]:
        result = dict(value.__dict__)
        result["sources"] = list(value.sources)
        return result
