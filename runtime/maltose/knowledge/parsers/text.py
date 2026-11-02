"""Plain text document parser."""

from __future__ import annotations

from pathlib import Path

from maltose.knowledge.models import ParsedDocument


class TextParser:
    supported_extensions = (".txt",)

    def parse(self, path: Path) -> ParsedDocument:
        text = path.read_text(encoding="utf-8")
        return ParsedDocument(
            path=path,
            text=text,
            title=path.stem,
            file_type="txt",
            metadata={"encoding": "utf-8"},
        )
