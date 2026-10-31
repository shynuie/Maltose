"""Bridge filesystem approval records to the existing UI confirmation blocks."""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

from myagent.filesystem.approval import ApprovalManager, ApprovalRecord


class FilesystemApprovalUI:
    """Publish and consume scoped filesystem approval UI actions."""

    def __init__(
        self,
        manager: ApprovalManager,
        *,
        session_id: str,
        publisher: Callable[[str, dict[str, Any]], Any],
    ) -> None:
        self.manager = manager
        self.session_id = session_id
        self.publisher = publisher

    def publish_request(self, record: ApprovalRecord) -> None:
        if record.session_id != self.session_id:
            raise PermissionError("Approval belongs to another session.")
        self.publisher("ui_confirmation", self._payload(
            record,
            title="Filesystem approval required",
            content=(
                f"Allow {record.operation} on {record.root}/{record.path}"
                + (f" to {record.destination_path}? " if record.destination_path else "? ")
                + "The operation is scoped to this exact path."
            ),
            actions=[
                {"id": "filesystem.approve", "label": "Approve"},
                {"id": "filesystem.reject", "label": "Reject"},
            ],
            status="pending",
        ))

    def handle_action(self, action_id: str, value: object) -> ApprovalRecord:
        if not isinstance(value, dict) or not isinstance(value.get("approval_id"), str):
            raise ValueError("Filesystem approval action requires approval_id.")
        approval_id = value["approval_id"]
        if action_id == "filesystem.approve":
            record = self.manager.approve(approval_id, session_id=self.session_id)
            status = "approved"
            content = "Approved. The original operation must consume this one-time approval."
        elif action_id == "filesystem.reject":
            record = self.manager.reject(approval_id, session_id=self.session_id)
            status = "rejected"
            content = "Rejected. No filesystem change was performed."
        else:
            raise ValueError(f"Unknown filesystem approval action: {action_id}")
        self.publisher("ui_confirmation", self._payload(
            record,
            title="Filesystem approval",
            content=content,
            actions=[],
            status=status,
        ))
        return record

    @staticmethod
    def _payload(
        record: ApprovalRecord,
        *,
        title: str,
        content: str,
        actions: list[dict[str, str]],
        status: str,
    ) -> dict[str, Any]:
        return {
            "block_id": f"filesystem-approval-{record.approval_id}",
            "approval_id": record.approval_id,
            "title": title,
            "content": content,
            "actions": actions,
            "value": {"approval_id": record.approval_id},
            "status": status,
        }
