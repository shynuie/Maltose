"""Safe document import and creation inside the managed document root."""

from __future__ import annotations

import shutil
from dataclasses import dataclass
from pathlib import Path

from maltose.knowledge.indexer import DocumentIndexer, IndexResult
from maltose.knowledge.models import ScannedFile
from maltose.knowledge.scanner import DocumentScanner


@dataclass(frozen=True)
class IngestionResult:
    path: Path
    index: IndexResult


class DocumentIngestionService:
    def __init__(self, *, documents_root: str | Path, scanner: DocumentScanner, indexer: DocumentIndexer) -> None:
        self.documents_root = Path(documents_root).expanduser().resolve()
        self.scanner = scanner
        self.indexer = indexer

    def import_file(self, source_path: str | Path, destination: str) -> IngestionResult:
        source = Path(source_path).expanduser().resolve()
        if not source.is_file():
            raise FileNotFoundError(source)
        target = self._safe_target(destination)
        if target.exists():
            raise FileExistsError(target)
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(source, target)
        return self._index_target(target)

    def create_document(
        self,
        *,
        content: str,
        filename: str,
        directory: str = "inbox",
    ) -> IngestionResult:
        if not content.strip():
            raise ValueError("Document content cannot be empty")
        target = self._safe_target(str(Path(directory) / filename))
        if target.suffix.lower() not in self.scanner.supported_extensions:
            raise ValueError(f"Unsupported document extension: {target.suffix or '<none>'}")
        if target.exists():
            raise FileExistsError(target)
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(content, encoding="utf-8")
        return self._index_target(target)

    def _safe_target(self, relative_destination: str) -> Path:
        destination = Path(relative_destination)
        if destination.is_absolute():
            raise PermissionError("Document destination must be relative to document root")
        target = (self.documents_root / destination).resolve()
        try:
            target.relative_to(self.documents_root)
        except ValueError as exc:
            raise PermissionError("Document destination escapes document root") from exc
        return target

    def _index_target(self, target: Path) -> IngestionResult:
        scanned = self.scanner.scan(self.documents_root).files
        matching = next((item for item in scanned if item.path == target), None)
        if matching is None:
            raise RuntimeError(f"Created document was not found by scanner: {target}")
        return IngestionResult(path=target, index=self.indexer.index(matching))
