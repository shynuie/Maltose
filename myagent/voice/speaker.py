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
    """Fallback until a concrete local speaker model is configured.

    When ``trusted_user_id`` is provided by the CLI, the application is
    explicitly running in single-user fallback mode, so the result is treated
    as identified even though no acoustic verification score exists.
    """

    def __init__(self, trusted_user_id: str | None = None) -> None:
        self.trusted_user_id = trusted_user_id

    def identify(self, audio_path: Path) -> SpeakerResult:
        if self.trusted_user_id:
            return SpeakerResult(
                user_id=self.trusted_user_id,
                score=None,
                status="identified",
            )
        return SpeakerResult(user_id=None, score=None, status="unknown")
