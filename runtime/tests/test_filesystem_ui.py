from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from maltose.filesystem.approval import ApprovalManager
from maltose.filesystem.ui import FilesystemApprovalUI


class FilesystemApprovalUITests(unittest.TestCase):
    def test_request_publishes_confirmation_and_action_is_scoped(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            manager = ApprovalManager(Path(directory) / "approvals.json")
            published: list[tuple[str, dict[str, object]]] = []
            bridge = FilesystemApprovalUI(
                manager,
                session_id="session-1",
                publisher=lambda block_type, payload: published.append((block_type, payload)),
            )
            record = manager.create(
                session_id="session-1",
                operation="delete",
                root="workspace",
                path="old.txt",
            )

            bridge.publish_request(record)
            self.assertEqual(published[0][0], "ui_confirmation")
            self.assertEqual(published[0][1]["approval_id"], record.approval_id)

            with self.assertRaises(KeyError):
                bridge.handle_action("filesystem.approve", {"approval_id": "wrong"})
            approved = bridge.handle_action(
                "filesystem.approve", {"approval_id": record.approval_id}
            )
            self.assertEqual(approved.status, "approved")
            self.assertEqual(published[-1][1]["status"], "approved")

    def test_reject_action_does_not_approve_record(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            manager = ApprovalManager(Path(directory) / "approvals.json")
            bridge = FilesystemApprovalUI(
                manager,
                session_id="session-1",
                publisher=lambda *_: None,
            )
            record = manager.create(
                session_id="session-1",
                operation="delete",
                root="workspace",
                path="old.txt",
            )

            rejected = bridge.handle_action(
                "filesystem.reject", {"approval_id": record.approval_id}
            )

            self.assertEqual(rejected.status, "rejected")
            with self.assertRaises(PermissionError):
                manager.approve(record.approval_id, session_id="session-1")


if __name__ == "__main__":
    unittest.main()
