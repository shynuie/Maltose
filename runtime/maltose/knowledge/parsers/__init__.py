"""Document format parsers."""

from maltose.knowledge.parsers.base import DocumentParser, ParserRegistry
from maltose.knowledge.parsers.markdown import MarkdownParser
from maltose.knowledge.parsers.pdf import PDFParser
from maltose.knowledge.parsers.text import TextParser

__all__ = ["DocumentParser", "MarkdownParser", "PDFParser", "ParserRegistry", "TextParser"]
