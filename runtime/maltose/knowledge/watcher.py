"""Filesystem watcher abstractions for the document knowledge base.

The first implementation intentionally uses polling and the existing scanner.
It keeps indexing independent from a platform-specific watcher library while
providing an event contract that can later be backed by native filesystem
notifications.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from enum import StrEnum
from pathlib import Path
from typing import Protocol

from maltose.knowledge.models import ScannedFile
from maltose.knowledge.scanner import DocumentScanner

logger = logging.getLogger(__name__)


class DocumentWatchEventType(StrEnum):
    CREATED = "created"
    MODIFIED = "modified"
    DELETED = "deleted"
    MOVED = "moved"


@dataclass(frozen=True)
class DocumentWatchEvent:
    """A source-file change observed below the managed document root."""

    type: DocumentWatchEventType
    path: Path
    scanned_file: ScannedFile | None = None
    previous_path: Path | None = None
    previous_hash: str | None = None


class DocumentWatcher(Protocol):
    """Minimal lifecycle contract consumed by a future indexing worker."""

    def start(self) -> None:
        """Capture the initial snapshot without emitting events."""

    def poll(self) -> tuple[DocumentWatchEvent, ...]:
        """Return changes since the previous snapshot."""

    def stop(self) -> None:
        """Release watcher resources and make the watcher inactive."""


class PollingDocumentWatcher:
    """Detect document changes by rescanning the managed root on demand."""

    def __init__(self, root: Path, scanner: DocumentScanner | None = None) -> None:
        self.root = root.expanduser().resolve()
        self.scanner = scanner or DocumentScanner()
        self._snapshot: dict[str, ScannedFile] = {}
        self._started = False

    def start(self) -> None:
        self._snapshot = self._scan_snapshot()
        self._started = True
        logger.info(
            "kdb_watcher_started root=%s tracked_files=%d",
            self.root,
            len(self._snapshot),
        )

    def poll(self) -> tuple[DocumentWatchEvent, ...]:
        if not self._started:
            self.start()
            return ()

        current = self._scan_snapshot()
        previous = self._snapshot
        events: list[DocumentWatchEvent] = []

        removed = {key: value for key, value in previous.items() if key not in current}
        added = {key: value for key, value in current.items() if key not in previous}

        # A same-content removal/addition is a move, so the future queue can
        # preserve the existing document id and avoid re-embedding it.
        added_by_hash: dict[str, list[ScannedFile]] = {}
        for scanned in added.values():
            added_by_hash.setdefault(scanned.content_hash, []).append(scanned)
        moved_removed: set[str] = set()
        moved_added: set[str] = set()
        for old_key, old_file in removed.items():
            candidates = added_by_hash.get(old_file.content_hash, [])
            if not candidates:
                continue
            new_file = candidates.pop(0)
            moved_removed.add(old_key)
            moved_added.add(new_file.relative_path)
            events.append(
                DocumentWatchEvent(
                    type=DocumentWatchEventType.MOVED,
                    path=new_file.path,
                    scanned_file=new_file,
                    previous_path=old_file.path,
                    previous_hash=old_file.content_hash,
                )
            )

        for key, scanned in added.items():
            if key not in moved_added:
                events.append(
                    DocumentWatchEvent(
                        type=DocumentWatchEventType.CREATED,
                        path=scanned.path,
                        scanned_file=scanned,
                    )
                )
        for key, scanned in removed.items():
            if key not in moved_removed:
                events.append(
                    DocumentWatchEvent(
                        type=DocumentWatchEventType.DELETED,
                        path=scanned.path,
                        previous_hash=scanned.content_hash,
                    )
                )
        for key, scanned in current.items():
            old_file = previous.get(key)
            if old_file is not None and old_file.content_hash != scanned.content_hash:
                events.append(
                    DocumentWatchEvent(
                        type=DocumentWatchEventType.MODIFIED,
                        path=scanned.path,
                        scanned_file=scanned,
                        previous_hash=old_file.content_hash,
                    )
                )

        self._snapshot = current
        logger.debug(
            "kdb_watcher_polled root=%s events=%d",
            self.root,
            len(events),
        )
        return tuple(events)

    def stop(self) -> None:
        self._snapshot = {}
        self._started = False
        logger.info("kdb_watcher_stopped root=%s", self.root)

    def _scan_snapshot(self) -> dict[str, ScannedFile]:
        result = self.scanner.scan(self.root, verbose=False)
        return {scanned.relative_path: scanned for scanned in result.files}
