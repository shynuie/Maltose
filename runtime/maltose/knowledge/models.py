"""Format-neutral models used by the Document Knowledge Base."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any


@dataclass(frozen=True)
class DocumentLocation:
    """A source location that can be used to read original document content."""

    page: int | None = None
    section: str | None = None
    start_offset: int | None = None
    end_offset: int | None = None


@dataclass(frozen=True)
class ParsedPage:
    page: int
    text: str
    start_offset: int | None = None
    end_offset: int | None = None


@dataclass(frozen=True)
class ParsedSection:
    title: str
    text: str
    start_offset: int
    end_offset: int


@dataclass(frozen=True)
class ParsedDocument:
    """Unified parser output independent of the source file format."""

    path: Path
    text: str
    title: str | None
    file_type: str
    pages: tuple[ParsedPage, ...] = ()
    sections: tuple[ParsedSection, ...] = ()
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class DocumentChunk:
    """A retrieval unit with enough information to locate source content."""

    chunk_index: int
    text: str
    start_offset: int
    end_offset: int
    page: int | None = None
    section: str | None = None
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class ScannedFile:
    path: Path
    relative_path: str
    filename: str
    file_type: str
    content_hash: str
    file_size: int
    modified_at: datetime
