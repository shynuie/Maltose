"""Offline summary provider used by the first local indexing CLI."""

from __future__ import annotations

from myagent.knowledge.models import ParsedDocument


class ExtractiveDocumentSummarizer:
    def __init__(self, max_chars: int = 500) -> None:
        if max_chars < 1:
            raise ValueError("max_chars must be positive")
        self.max_chars = max_chars

    def summarize(self, document: ParsedDocument) -> str:
        compact = " ".join(document.text.split())
        if not compact:
            return document.title or document.path.stem
        return compact[: self.max_chars]
