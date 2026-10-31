"""Provider-neutral embedding interface for KDB."""

from __future__ import annotations

from collections.abc import Callable
from typing import Protocol


class EmbeddingProvider(Protocol):
    def embed(self, text: str) -> list[float]:
        ...


class LazyEmbeddingProvider:
    """Instantiate an embedding provider only on the first embed call."""

    def __init__(self, factory: Callable[[], EmbeddingProvider]) -> None:
        self._factory = factory
        self._provider: EmbeddingProvider | None = None

    def embed(self, text: str) -> list[float]:
        if self._provider is None:
            self._provider = self._factory()
        return self._provider.embed(text)
