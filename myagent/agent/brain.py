from __future__ import annotations

from typing import Protocol


class AgentBrain(Protocol):
    """Abstract protocol for agent thinking / response generation."""

    def process(self, user_text: str) -> str:
        """Process user text and return the response text to speak."""
        ...


class EchoBrain:
    """Minimal brain for Phase 1 that echoes the transcribed text."""

    def __init__(self, prefix: str = "收到，你說：") -> None:
        self._prefix = prefix

    def process(self, user_text: str) -> str:
        return f"{self._prefix}{user_text}"
