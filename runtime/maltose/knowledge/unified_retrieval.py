"""Unified truth-first retrieval with explicit provenance labels."""

from __future__ import annotations

from typing import Any

from maltose.agent.capabilities import CapabilityTool
from maltose.knowledge.curation import CuratedKnowledgeStore
from maltose.knowledge.retrieval import DocumentKnowledgeService


class UnifiedKnowledgeService:
    def __init__(
        self,
        *,
        truth: DocumentKnowledgeService,
        curated: CuratedKnowledgeStore | None = None,
    ) -> None:
        self.truth = truth
        self.curated = curated

    def search(
        self,
        query: str,
        *,
        top_k: int = 5,
        include_uncertain: bool = False,
    ) -> list[dict[str, Any]]:
        if not query.strip():
            raise ValueError("Knowledge query cannot be empty.")
        if top_k <= 0:
            raise ValueError("top_k must be positive.")
        truth_results = [
            {
                "source_type": "truth",
                "document_id": item.document_id,
                "title": item.title,
                "path": item.path,
                "summary": item.summary,
                "similarity_score": item.similarity_score,
                "metadata": item.metadata,
            }
            for item in self.truth.search_documents(query, top_k=top_k)
        ]
        if len(truth_results) >= top_k or self.curated is None:
            return truth_results[:top_k]
        curated_results = self.curated.search(
            query,
            top_k=top_k - len(truth_results),
            include_uncertain=include_uncertain,
        )
        return truth_results + curated_results


class UnifiedKnowledgeToolAdapter:
    def __init__(self, service: UnifiedKnowledgeService) -> None:
        self.service = service

    def tools(self) -> list[CapabilityTool]:
        return [CapabilityTool(
            name="search_knowledge",
            description="Search truth documents first, then approved Agent-curated knowledge. Every result includes source_type.",
            parameters={
                "type": "object",
                "properties": {
                    "query": {"type": "string"},
                    "top_k": {"type": "integer", "minimum": 1, "maximum": 20},
                    "include_uncertain": {"type": "boolean", "default": False},
                },
                "required": ["query"],
            },
            handler=lambda arguments: self.service.search(
                arguments["query"],
                top_k=int(arguments.get("top_k", 5)),
                include_uncertain=bool(arguments.get("include_uncertain", False)),
            ),
        )]
