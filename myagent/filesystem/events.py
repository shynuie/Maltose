"""Typed mutation events emitted after controlled filesystem changes."""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum
from pathlib import Path
from typing import Callable


class FilesystemMutationType(StrEnum):
    CREATED = "created"
    MODIFIED = "modified"
    COPIED = "copied"
    TRASHED = "trashed"
    RESTORED = "restored"
    MOVED = "moved"


@dataclass(frozen=True)
class FilesystemMutationEvent:
    type: FilesystemMutationType
    root: str
    path: Path
    relative_path: str
    operation_id: str | None = None
    source_root: str | None = None
    source_path: str | None = None


FilesystemMutationObserver = Callable[[FilesystemMutationEvent], None]
