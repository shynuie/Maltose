"""Web UI bridge for command execution and artifact approvals."""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

from myagent.filesystem.approval import ApprovalManager, ApprovalRecord


class ExecutionApprovalUI:
    def __init__(
        self,
        manager: ApprovalManager,
        *,
        session_id: str,
        publisher: Callable[[str, dict[str, Any]], Any],
        execution_resumer: Callable[[str], dict[str, object]] | None = None,
    ) -> None:
        self.manager = manager
        self.session_id = session_id
        self.publisher = publisher
        self.execution_resumer = execution_resumer

    def publish_request(self, record: ApprovalRecord) -> None:
        if record.session_id != self.session_id:
            raise PermissionError("Approval belongs to another session.")
        destination = f" → {record.destination_path}" if record.destination_path else ""
        self.publisher("ui_confirmation", {
            "block_id": f"execution-approval-{record.approval_id}",
            "approval_id": record.approval_id,
            "title": "Command execution approval required",
            "content": f"Allow {record.operation} {record.root}/{record.path}{destination}?",
            "actions": [
                {"id": "execution.approve", "label": "Approve"},
                {"id": "execution.reject", "label": "Reject"},
            ],
            "value": {"approval_id": record.approval_id},
            "status": "pending",
        })

    def handle_action(self, action_id: str, value: object) -> ApprovalRecord:
        if not isinstance(value, dict) or not isinstance(value.get("approval_id"), str):
            raise ValueError("Execution approval action requires approval_id.")
        approval_id = value["approval_id"]
        if action_id == "execution.approve":
            record = self.manager.approve(approval_id, session_id=self.session_id)
            if record.operation == "promote" and self.execution_resumer is not None:
                self.execution_resumer(approval_id)
            status, content = "approved", "Approved. The original execution must consume this approval."
        elif action_id == "execution.reject":
            record = self.manager.reject(approval_id, session_id=self.session_id)
            status, content = "rejected", "Rejected. No execution or promotion was performed."
        else:
            raise ValueError(f"Unknown execution approval action: {action_id}")
        self.publisher("ui_confirmation", {
            "block_id": f"execution-approval-{record.approval_id}",
            "approval_id": record.approval_id,
            "title": "Command execution approval",
            "content": content,
            "actions": [],
            "value": {"approval_id": record.approval_id},
            "status": status,
        })
        return record
