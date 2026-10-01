from __future__ import annotations

import hashlib
import tempfile
import unittest
from pathlib import Path

from myagent.filesystem.paths import FilesystemRoot, PathResolver
from myagent.filesystem.approval import ApprovalManager
from myagent.filesystem.policy import ApprovalRequired, PolicyEngine, WorkingRoot
from myagent.filesystem.service import FileService


class FileServiceWriteTests(unittest.TestCase):
    def make_service(self, directory: str) -> tuple[Path, Path, FileService]:
        base = Path(directory)
        workspace = base / "workspace"
        documents = base / "documents"
        workspace.mkdir()
        documents.mkdir()
        resolver = PathResolver({
            "workspace": FilesystemRoot("workspace", workspace, read=True, write=True, delete=True),
            "documents": FilesystemRoot("documents", documents, read=True, write=False, delete=False),
        })
        policy = PolicyEngine(resolver, working_root=WorkingRoot("workspace"))
        return workspace, documents, FileService(
            resolver, policy, approval_manager=ApprovalManager(base / "approvals.json"),
            session_id="session-1",
        )

    def test_create_write_and_replace_text_stay_inside_working_root(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            workspace, _, service = self.make_service(directory)

            created = service.create_file("workspace", "notes/a.txt", "hello world")
            updated = service.replace_text(
                "workspace",
                "notes/a.txt",
                "world",
                "agent",
                expected_sha256=created["sha256"],
            )

            self.assertEqual((workspace / "notes/a.txt").read_text(encoding="utf-8"), "hello agent")
            self.assertNotEqual(created["sha256"], updated["sha256"])

    def test_overwrite_requires_matching_hash(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            workspace, _, service = self.make_service(directory)
            path = workspace / "note.txt"
            path.write_text("old", encoding="utf-8")
            expected = hashlib.sha256(b"old").hexdigest()
            path.write_text("user changed", encoding="utf-8")

            with self.assertRaises(RuntimeError):
                service.write_file("workspace", "note.txt", "agent changed", expected_sha256=expected)

    def test_readable_source_can_be_copied_but_not_moved(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            workspace, documents, service = self.make_service(directory)
            source = documents / "reference.txt"
            source.write_text("reference", encoding="utf-8")

            result = service.copy_file(
                "documents", "reference.txt", "workspace", "reference.txt"
            )
            self.assertEqual(result["path"], "reference.txt")
            self.assertTrue((workspace / "reference.txt").exists())

            with self.assertRaises(PermissionError):
                service.move_file("documents", "reference.txt", "workspace", "moved.txt")
            self.assertTrue(source.exists())

    def test_write_outside_working_root_is_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            _, documents, service = self.make_service(directory)

            with self.assertRaises(PermissionError):
                service.create_file("documents", "new.txt", "no")
            self.assertFalse((documents / "new.txt").exists())

    def test_delete_and_move_are_not_executed_without_approval(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            workspace, _, service = self.make_service(directory)
            (workspace / "a.txt").write_text("a", encoding="utf-8")

            with self.assertRaises(ApprovalRequired) as context:
                service.move_file("workspace", "a.txt", "workspace", "b.txt")
            self.assertTrue((workspace / "a.txt").exists())
            self.assertIsNotNone(context.exception.approval_id)


if __name__ == "__main__":
    unittest.main()
