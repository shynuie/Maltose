from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from myagent.filesystem.config import FilesystemConfig


class FilesystemConfigTests(unittest.TestCase):
    def test_builds_named_roots_and_working_root(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            config = FilesystemConfig.from_mapping({
                "filesystem": {
                    "roots": {
                        "workspace": {"path": str(Path(directory) / "work"), "read": True, "write": True, "delete": True},
                        "documents": {"path": str(Path(directory) / "docs"), "read": True},
                    },
                    "working_root": {"root": "workspace", "path": "."},
                    "protected_paths": [".env", "secrets/*"],
                }
            })
            resolver = config.resolver()
            self.assertEqual(resolver.root("workspace").path, (Path(directory) / "work").resolve())
            self.assertEqual(config.policy().working_root.root, "workspace")

    def test_rejects_non_writable_working_root_and_invalid_limits(self) -> None:
        with self.assertRaises(ValueError):
            FilesystemConfig.from_mapping({
                "roots": {"documents": {"path": "documents", "read": True}},
                "working_root": "documents",
            })
        with self.assertRaises(ValueError):
            FilesystemConfig.from_mapping({
                "roots": {"workspace": {"path": "workspace", "write": True, "delete": True}},
                "working_root": "workspace", "max_read_bytes": 0,
            })


if __name__ == "__main__":
    unittest.main()
