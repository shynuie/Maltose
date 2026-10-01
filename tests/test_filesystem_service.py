from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from myagent.filesystem.paths import FilesystemRoot, PathResolver
from myagent.filesystem.policy import PolicyEngine
from myagent.filesystem.service import FileService
from myagent.filesystem.tools import FileToolAdapter


class FileServiceTests(unittest.TestCase):
    def make_service(self, directory: str) -> tuple[Path, FileService]:
        root = Path(directory) / "workspace"
        root.mkdir()
        resolver = PathResolver({
            "workspace": FilesystemRoot("workspace", root, read=True, write=False, delete=False),
            "private": FilesystemRoot("private", Path(directory) / "private", read=False),
        }, protected_paths=(".env",))
        return root, FileService(resolver, PolicyEngine(resolver, max_read_bytes=32))

    def test_read_list_and_search_are_root_relative(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root, service = self.make_service(directory)
            (root / "notes").mkdir()
            (root / "notes/today.txt").write_text("Buy tea\nCall Alice\n", encoding="utf-8")

            content = service.read_file("workspace", "notes/today.txt")
            listing = service.list_files("workspace", recursive=True)
            matches = service.search_files("workspace", "alice")

            self.assertEqual(content["text"], "Buy tea\nCall Alice\n")
            self.assertEqual([item["path"] for item in listing], ["notes", "notes/today.txt"])
            self.assertEqual(matches[0]["path"], "notes/today.txt")
            self.assertEqual(matches[0]["line"], 2)

    def test_read_policy_rejects_disabled_root_and_large_file(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root, service = self.make_service(directory)
            (root / "large.txt").write_text("x" * 33, encoding="utf-8")

            with self.assertRaises(PermissionError):
                service.read_file("private", "secret.txt")
            with self.assertRaises(PermissionError):
                service.read_file("workspace", "large.txt")

    def test_adapter_exposes_only_read_tools(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            _, service = self.make_service(directory)

            tools = FileToolAdapter(service).tools()

            self.assertEqual(
                {tool.name for tool in tools},
                {
                    "read_file", "list_files", "search_files", "create_file", "write_file",
                    "replace_file_text", "copy_file", "move_file", "delete_file", "restore_file",
                },
            )


if __name__ == "__main__":
    unittest.main()
