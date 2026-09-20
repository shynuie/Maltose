"""Provider-neutral embedding interface for KDB."""

from __future__ import annotations

from typing import Protocol


class EmbeddingProvider(Protocol):
    def embed(self, text: str) -> list[float]:
        ...

