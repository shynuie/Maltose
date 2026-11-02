"""PDF parser with page-level source locations."""

from __future__ import annotations

from pathlib import Path

from maltose.knowledge.models import ParsedDocument, ParsedPage


class PDFParser:
    supported_extensions = (".pdf",)

    def parse(self, path: Path) -> ParsedDocument:
        try:
            from pypdf import PdfReader
        except ImportError as exc:
            raise RuntimeError(
                "PDF support requires the 'pypdf' package."
            ) from exc

        reader = PdfReader(str(path))
        parts: list[str] = []
        pages: list[ParsedPage] = []
        offset = 0
        for page_number, page in enumerate(reader.pages, start=1):
            page_text = page.extract_text() or ""
            if parts:
                parts.append("\n\n")
                offset += 2
            start = offset
            parts.append(page_text)
            offset += len(page_text)
            pages.append(
                ParsedPage(
                    page=page_number,
                    text=page_text,
                    start_offset=start,
                    end_offset=offset,
                )
            )

        text = "".join(parts)
        metadata = dict(reader.metadata or {})
        title = metadata.get("/Title") or path.stem
        return ParsedDocument(
            path=path,
            text=text,
            title=str(title),
            file_type="pdf",
            pages=tuple(pages),
            metadata={"pdf_metadata": metadata},
        )
