from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Literal, Protocol


@dataclass(frozen=True)
class SpeakerResult:
    user_id: str | None
    score: float | None
    status: Literal["identified", "unknown", "ambiguous"]


class SpeakerIdentifier(Protocol):
    def identify(self, audio_path: Path) -> SpeakerResult:
        """Identify the speaker from a completed utterance recording."""
        ...


class NullSpeakerIdentifier:
    """Fallback until a concrete local speaker model is configured."""

    def identify(self, audio_path: Path) -> SpeakerResult:
        return SpeakerResult(user_id="default", score=None, status="unknown")
