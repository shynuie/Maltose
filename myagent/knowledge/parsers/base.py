"""Parser interfaces and extension-based parser dispatch."""

from __future__ import annotations

from pathlib import Path
from typing import Protocol

from myagent.knowledge.models import ParsedDocument


class DocumentParser(Protocol):
    supported_extensions: tuple[str, ...]

    def parse(self, path: Path) -> ParsedDocument:
        ...


class ParserRegistry:
    """Select a parser by normalized file extension."""

    def __init__(self, parsers: list[DocumentParser] | None = None) -> None:
        self._parsers: dict[str, DocumentParser] = {}
        for parser in parsers or []:
            self.register(parser)

    def register(self, parser: DocumentParser) -> None:
        for extension in parser.supported_extensions:
            normalized = extension.lower()
            if not normalized.startswith("."):
                raise ValueError(f"Parser extension must start with '.': {extension}")
            if normalized in self._parsers:
                raise ValueError(f"A parser is already registered for {normalized}")
            self._parsers[normalized] = parser

    def parser_for(self, path: Path) -> DocumentParser:
        extension = path.suffix.lower()
        try:
            return self._parsers[extension]
        except KeyError as exc:
            supported = ", ".join(sorted(self._parsers)) or "none"
            raise ValueError(
                f"Unsupported document type {extension or '<none>'}; supported: {supported}"
            ) from exc

    def parse(self, path: Path) -> ParsedDocument:
        return self.parser_for(path).parse(path)
