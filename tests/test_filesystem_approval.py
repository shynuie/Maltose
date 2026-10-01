from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from myagent.filesystem.approval import ApprovalManager, AuditLog
from myagent.filesystem.paths import FilesystemRoot, PathResolver
from myagent.filesystem.policy import ApprovalRequired, PolicyEngine, WorkingRoot
from myagent.filesystem.service import FileService


class FilesystemApprovalTests(unittest.TestCase):
    def make_service(self, directory: str) -> tuple[Path, FileService, ApprovalManager]:
        base = Path(directory)
        workspace = base / "workspace"
        workspace.mkdir()
        resolver = PathResolver({
            "workspace": FilesystemRoot("workspace", workspace, read=True, write=True, delete=True),
        })
        approvals = ApprovalManager(base / "approvals.json")
        service = FileService(
            resolver,
            PolicyEngine(resolver, working_root=WorkingRoot("workspace")),
            approval_manager=approvals,
            audit_log=AuditLog(base / "audit.jsonl"),
            session_id="session-1",
            trash_path=base / "trash",
        )
        return workspace, service, approvals

    def test_delete_creates_pending_approval_without_touching_file(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            workspace, service, _ = self.make_service(directory)
            path = workspace / "remove.txt"
            path.write_text("remove me", encoding="utf-8")

            with self.assertRaises(ApprovalRequired) as context:
                service.delete_file("workspace", "remove.txt")

            self.assertIsNotNone(context.exception.approval_id)
            self.assertTrue(path.exists())

    def test_approved_delete_moves_to_trash_and_restore_recovers_file(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            workspace, service, approvals = self.make_service(directory)
            path = workspace / "remove.txt"
            path.write_text("remove me", encoding="utf-8")

            with self.assertRaises(ApprovalRequired) as context:
                service.delete_file("workspace", "remove.txt")
            approval_id = context.exception.approval_id
            self.assertIsNotNone(approval_id)
            approvals.approve(approval_id, session_id="session-1")
            result = service.delete_file(
                "workspace", "remove.txt", approval_id=approval_id
            )

            self.assertFalse(path.exists())
            self.assertEqual(result["status"], "trashed")
            restored = service.restore_file(result["operation_id"])
            self.assertEqual(restored["status"], "restored")
            self.assertEqual(path.read_text(encoding="utf-8"), "remove me")

    def test_approval_is_one_time_and_session_scoped(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            approvals = ApprovalManager(Path(directory) / "approvals.json")
            record = approvals.create(
                session_id="one",
                operation="delete",
                root="workspace",
                path="a.txt",
            )
            with self.assertRaises(PermissionError):
                approvals.approve(record.approval_id, session_id="two")
            approvals.approve(record.approval_id, session_id="one")
            approvals.consume(
                record.approval_id,
                session_id="one",
                operation="delete",
                root="workspace",
                path="a.txt",
            )
            with self.assertRaises(PermissionError):
                approvals.consume(
                    record.approval_id,
                    session_id="one",
                    operation="delete",
                    root="workspace",
                    path="a.txt",
                )

    def test_approved_move_binds_source_destination_and_hash(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            workspace, service, approvals = self.make_service(directory)
            source = workspace / "a.txt"
            source.write_text("move me", encoding="utf-8")

            with self.assertRaises(ApprovalRequired) as context:
                service.move_file("workspace", "a.txt", "workspace", "b.txt")
            approval_id = context.exception.approval_id
            self.assertIsNotNone(approval_id)
            approvals.approve(approval_id, session_id="session-1")
            result = service.move_file(
                "workspace", "a.txt", "workspace", "b.txt", approval_id=approval_id
            )

            self.assertEqual(result["path"], "b.txt")
            self.assertFalse(source.exists())
            self.assertEqual((workspace / "b.txt").read_text(encoding="utf-8"), "move me")

    def test_restore_rejects_trash_path_traversal(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            _, service, _ = self.make_service(directory)

            with self.assertRaises(PermissionError):
                service.restore_file("../outside")


if __name__ == "__main__":
    unittest.main()
