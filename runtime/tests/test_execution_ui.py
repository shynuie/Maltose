from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from myagent.execution.ui import ExecutionApprovalUI
from myagent.filesystem.approval import ApprovalManager


class ExecutionApprovalUITests(unittest.TestCase):
    def test_publish_and_handle_approval(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            manager = ApprovalManager(Path(directory) / "approvals.json")
            record = manager.create(
                session_id="session-1", operation="execute", root="execution", path="scope",
                destination_path="network:restricted",
            )
            published: list[tuple[str, dict[str, object]]] = []
            ui = ExecutionApprovalUI(
                manager, session_id="session-1",
                publisher=lambda block_type, payload: published.append((block_type, payload)),
            )
            ui.publish_request(record)
            self.assertEqual(published[0][0], "ui_confirmation")
            approved = ui.handle_action("execution.approve", {"approval_id": record.approval_id})
            self.assertEqual(approved.status, "approved")
            self.assertEqual(published[-1][1]["status"], "approved")


if __name__ == "__main__":
    unittest.main()
