from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from maltose.execution.backend import BackendCapabilities, MountSpec


class ExecutionBackendBoundaryTests(unittest.TestCase):
    def test_mount_requires_absolute_source_and_target(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            mount = MountSpec(Path(directory).resolve(), "/workspace", read_only=False)
            self.assertFalse(mount.read_only)
        with self.assertRaises(ValueError):
            MountSpec(Path("relative"), "/workspace")
        with self.assertRaises(ValueError):
            MountSpec(Path.cwd().resolve(), "workspace")
        with self.assertRaises(ValueError):
            MountSpec(Path.cwd().resolve(), "/workspace/../private")

    def test_mount_rejects_symlink_source(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            source = Path(directory) / "source"
            target = Path(directory) / "target"
            target.mkdir()
            source.symlink_to(target, target_is_directory=True)
            with self.assertRaises(PermissionError):
                MountSpec(source, "/workspace")

    def test_capabilities_are_explicit(self) -> None:
        capabilities = BackendCapabilities("test", True, True, True, True)
        self.assertEqual(capabilities.name, "test")
        self.assertTrue(capabilities.supports_network_isolation)
        self.assertFalse(capabilities.supports_restricted_network)


if __name__ == "__main__":
    unittest.main()
