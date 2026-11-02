"""Markdown parser preserving heading-based sections and offsets."""

from __future__ import annotations

import re
from pathlib import Path

from maltose.knowledge.models import ParsedDocument, ParsedSection


_HEADING = re.compile(r"^(#{1,6})\s+(.+?)\s*$", re.MULTILINE)


class MarkdownParser:
    supported_extensions = (".md", ".markdown")

    def parse(self, path: Path) -> ParsedDocument:
        text = path.read_text(encoding="utf-8")
        matches = list(_HEADING.finditer(text))
        sections: list[ParsedSection] = []
        for index, match in enumerate(matches):
            start = match.start()
            end = matches[index + 1].start() if index + 1 < len(matches) else len(text)
            sections.append(
                ParsedSection(
                    title=match.group(2),
                    text=text[start:end],
                    start_offset=start,
                    end_offset=end,
                )
            )

        title = sections[0].title if sections else path.stem
        return ParsedDocument(
            path=path,
            text=text,
            title=title,
            file_type="markdown",
            sections=tuple(sections),
            metadata={"encoding": "utf-8"},
        )
