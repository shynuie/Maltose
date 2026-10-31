"""Read authoritative content from the managed document root."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from myagent.knowledge.models import DocumentLocation
from myagent.knowledge.parsers.base import ParserRegistry
from myagent.knowledge.repositories.metadata import MetadataRepository


@dataclass(frozen=True)
class SourceContent:
    document_id: str
    path: Path
    text: str
    location: DocumentLocation | None = None


class SourceReader:
    def __init__(self, *, metadata: MetadataRepository, documents_root: str | Path, parsers: ParserRegistry) -> None:
        self.metadata = metadata
        self.documents_root = Path(documents_root).expanduser().resolve()
        self.parsers = parsers

    def read(
        self,
        document_id: str,
        location: DocumentLocation | None = None,
    ) -> SourceContent:
        record = self.metadata.get_by_id(document_id)
        if record is None:
            raise KeyError(f"Unknown document: {document_id}")
        path = Path(record["path"]).expanduser().resolve()
        self._validate_path(path)
        if not path.is_file():
            raise FileNotFoundError(path)

        parsed = self.parsers.parse(path)
        text = parsed.text
        if location is not None:
            text = self._read_location(parsed, location)
        return SourceContent(document_id=document_id, path=path, text=text, location=location)

    def _validate_path(self, path: Path) -> None:
        try:
            path.relative_to(self.documents_root)
        except ValueError as exc:
            raise PermissionError(f"Document path is outside the configured root: {path}") from exc

    @staticmethod
    def _read_location(parsed, location: DocumentLocation) -> str:
        if location.page is not None:
            pages = [page for page in parsed.pages if page.page == location.page]
            if not pages:
                raise ValueError(f"Page is unavailable for this document: {location.page}")
            return pages[0].text
        if location.section is not None:
            sections = [section for section in parsed.sections if section.title == location.section]
            if not sections:
                raise ValueError(f"Section not found: {location.section}")
            return sections[0].text
        if location.start_offset is not None or location.end_offset is not None:
            start = location.start_offset or 0
            end = location.end_offset if location.end_offset is not None else len(parsed.text)
            if start < 0 or end < start or end > len(parsed.text):
                raise ValueError("Invalid document offsets")
            return parsed.text[start:end]
        return parsed.text
