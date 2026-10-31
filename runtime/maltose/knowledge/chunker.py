"""Format-neutral document chunking with source offsets."""

from __future__ import annotations

from maltose.knowledge.models import DocumentChunk, ParsedDocument


class DocumentChunker:
    """Split parsed text into overlapping character windows.

    Character offsets are intentionally kept in the original parsed text so a
    source reader can later use them to retrieve authoritative content.
    """

    def __init__(self, *, chunk_size: int = 1200, chunk_overlap: int = 150) -> None:
        if chunk_size <= 0:
            raise ValueError("chunk_size must be positive")
        if chunk_overlap < 0 or chunk_overlap >= chunk_size:
            raise ValueError("chunk_overlap must be between 0 and chunk_size - 1")
        self.chunk_size = chunk_size
        self.chunk_overlap = chunk_overlap

    def chunk(self, document: ParsedDocument) -> list[DocumentChunk]:
        text = document.text
        if not text:
            return []

        step = self.chunk_size - self.chunk_overlap
        chunks: list[DocumentChunk] = []
        start = 0
        while start < len(text):
            end = min(start + self.chunk_size, len(text))
            chunk_text = text[start:end]
            chunks.append(
                DocumentChunk(
                    chunk_index=len(chunks),
                    text=chunk_text,
                    start_offset=start,
                    end_offset=end,
                    page=self._page_for(document, start),
                    section=self._section_for(document, start),
                    metadata={"source_path": str(document.path)},
                )
            )
            if end == len(text):
                break
            start += step
        return chunks

    @staticmethod
    def _section_for(document: ParsedDocument, offset: int) -> str | None:
        for section in reversed(document.sections):
            if section.start_offset <= offset:
                return section.title
        return None

    @staticmethod
    def _page_for(document: ParsedDocument, offset: int) -> int | None:
        for page in reversed(document.pages):
            if page.start_offset is not None and page.start_offset <= offset:
                return page.page
        return None
