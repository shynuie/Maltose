"""Provider-neutral document summary interface."""

from __future__ import annotations

from typing import Protocol

from myagent.knowledge.models import ParsedDocument


class DocumentSummarizer(Protocol):
    def summarize(self, document: ParsedDocument) -> str:
        ...

