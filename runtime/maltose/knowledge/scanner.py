"""Filesystem scanning and content fingerprinting for KDB documents."""

from __future__ import annotations

import hashlib
import logging
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

from maltose.knowledge.models import ScannedFile

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class ScanPlan:
    new_files: tuple[ScannedFile, ...] = ()
    changed_files: tuple[ScannedFile, ...] = ()
    unchanged_files: tuple[ScannedFile, ...] = ()
    moved_document_ids: tuple[str, ...] = ()
    deleted_document_ids: tuple[str, ...] = ()


@dataclass(frozen=True)
class ScanResult:
    files: tuple[ScannedFile, ...]


class DocumentScanner:
    def __init__(self, supported_extensions: tuple[str, ...] = (".pdf", ".txt", ".md")) -> None:
        normalized = tuple(extension.lower() for extension in supported_extensions)
        if any(not extension.startswith(".") for extension in normalized):
            raise ValueError("supported extensions must start with '.'")
        self.supported_extensions = frozenset(normalized)

    def scan(self, root: Path, *, verbose: bool = True) -> ScanResult:
        root = root.expanduser().resolve()
        log = logger.info if verbose else logger.debug
        log("kdb_scan_started root=%s", root)
        if not root.exists():
            raise FileNotFoundError(root)
        if not root.is_dir():
            raise NotADirectoryError(root)

        files: list[ScannedFile] = []
        for path in sorted(candidate for candidate in root.rglob("*") if candidate.is_file()):
            if path.suffix.lower() not in self.supported_extensions:
                continue
            stat = path.stat()
            files.append(
                ScannedFile(
                    path=path,
                    relative_path=path.relative_to(root).as_posix(),
                    filename=path.name,
                    file_type=path.suffix.lower().lstrip("."),
                    content_hash=self._hash(path),
                    file_size=stat.st_size,
                    modified_at=datetime.fromtimestamp(stat.st_mtime).astimezone(),
                )
            )
        result = ScanResult(files=tuple(files))
        log(
            "kdb_scan_completed root=%s supported_files=%d",
            root,
            len(result.files),
        )
        return result

    @staticmethod
    def _hash(path: Path, block_size: int = 1024 * 1024) -> str:
        digest = hashlib.sha256()
        with path.open("rb") as stream:
            while block := stream.read(block_size):
                digest.update(block)
        return digest.hexdigest()
