from __future__ import annotations

import os
import tempfile
import unittest
from pathlib import Path

from myagent.filesystem.paths import PathResolver


class PathResolverTests(unittest.TestCase):
    def make_resolver(self, directory: str) -> tuple[Path, PathResolver]:
        base = Path(directory)
        root = base / "workspace"
        root.mkdir()
        return root, PathResolver(
            {"workspace": root},
            protected_paths=(".env", "secrets/*"),
        )

    def test_resolves_root_relative_path(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root, resolver = self.make_resolver(directory)

            result = resolver.resolve("workspace", "notes/today.md")

            self.assertEqual(result.path, (root / "notes/today.md").resolve())
            self.assertEqual(result.relative_path, "notes/today.md")

    def test_rejects_absolute_and_parent_paths(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            _, resolver = self.make_resolver(directory)

            with self.assertRaises(PermissionError):
                resolver.resolve("workspace", "/tmp/outside.txt")
            with self.assertRaises(PermissionError):
                resolver.resolve("workspace", "notes/../outside.txt")

    def test_rejects_unknown_root_and_protected_paths(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            _, resolver = self.make_resolver(directory)

            with self.assertRaises(PermissionError):
                resolver.resolve("documents", "notes.md")
            with self.assertRaises(PermissionError):
                resolver.resolve("workspace", ".env")
            with self.assertRaises(PermissionError):
                resolver.resolve("workspace", "secrets/token.txt")

    def test_rejects_symlink_component_even_when_target_is_inside_root(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root, resolver = self.make_resolver(directory)
            target = root / "real"
            target.mkdir()
            link = root / "alias"
            try:
                link.symlink_to(target, target_is_directory=True)
            except OSError as exc:
                self.skipTest(f"Symlinks unavailable: {exc}")

            with self.assertRaises(PermissionError):
                resolver.resolve("workspace", "alias/file.txt")

    def test_rejects_hard_linked_existing_file(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root, resolver = self.make_resolver(directory)
            original = root / "original.txt"
            linked = root / "linked.txt"
            original.write_text("secret", encoding="utf-8")
            try:
                os.link(original, linked)
            except OSError as exc:
                self.skipTest(f"Hard links unavailable: {exc}")

            with self.assertRaises(PermissionError):
                resolver.resolve("workspace", "linked.txt", must_exist=True)

    def test_must_exist_rejects_missing_path(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            _, resolver = self.make_resolver(directory)

            with self.assertRaises(FileNotFoundError):
                resolver.resolve("workspace", "missing.txt", must_exist=True)


if __name__ == "__main__":
    unittest.main()
