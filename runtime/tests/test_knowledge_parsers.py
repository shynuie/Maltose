from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from maltose.knowledge.parsers import MarkdownParser, ParserRegistry, TextParser


class KnowledgeParserTests(unittest.TestCase):
    def test_text_parser_returns_format_neutral_document(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "notes.txt"
            path.write_text("第一行\n第二行", encoding="utf-8")

            document = TextParser().parse(path)

            self.assertEqual(document.file_type, "txt")
            self.assertEqual(document.title, "notes")
            self.assertEqual(document.text, "第一行\n第二行")

    def test_markdown_parser_preserves_heading_sections_and_offsets(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "plan.md"
            content = "# Overview\nintro\n\n## Design\ndetails\n"
            path.write_text(content, encoding="utf-8")

            document = MarkdownParser().parse(path)

            self.assertEqual(document.title, "Overview")
            self.assertEqual([section.title for section in document.sections], ["Overview", "Design"])
            for section in document.sections:
                self.assertEqual(content[section.start_offset : section.end_offset], section.text)

    def test_registry_dispatches_by_case_insensitive_extension(self) -> None:
        registry = ParserRegistry([TextParser(), MarkdownParser()])
        self.assertIsInstance(registry.parser_for(Path("FILE.TXT")), TextParser)
        self.assertIsInstance(registry.parser_for(Path("FILE.MD")), MarkdownParser)

    def test_registry_rejects_unsupported_extension(self) -> None:
        registry = ParserRegistry([TextParser()])
        with self.assertRaisesRegex(ValueError, "Unsupported document type"):
            registry.parser_for(Path("image.png"))


if __name__ == "__main__":
    unittest.main()
