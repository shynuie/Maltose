"""Persistent, scoped approval records for high-risk filesystem operations."""

from __future__ import annotations

import json
import threading
import time
import uuid
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any


@dataclass(frozen=True)
class ApprovalRecord:
    approval_id: str
    session_id: str
    operation: str
    root: str
    path: str
    expected_sha256: str | None
    expires_at: float
    status: str = "pending"
    destination_path: str | None = None


class ApprovalManager:
    """Store approvals with exact operation scope and one-time consumption."""

    def __init__(self, path: str | Path | None = None) -> None:
        self.path = Path(path) if path is not None else None
        self._lock = threading.RLock()
        self._records: dict[str, ApprovalRecord] = {}
        self._load()

    def create(
        self,
        *,
        session_id: str,
        operation: str,
        root: str,
        path: str,
        expected_sha256: str | None = None,
        destination_path: str | None = None,
        ttl_seconds: float = 300,
    ) -> ApprovalRecord:
        if not session_id or not operation or not root or not path:
            raise ValueError("Approval scope fields cannot be empty.")
        if ttl_seconds <= 0:
            raise ValueError("Approval TTL must be positive.")
        record = ApprovalRecord(
            approval_id=uuid.uuid4().hex,
            session_id=session_id,
            operation=operation,
            root=root,
            path=path,
            expected_sha256=expected_sha256,
            expires_at=time.time() + ttl_seconds,
            destination_path=destination_path,
        )
        with self._lock:
            self._records[record.approval_id] = record
            self._save()
        return record

    def approve(self, approval_id: str, *, session_id: str) -> ApprovalRecord:
        with self._lock:
            record = self._get_valid(approval_id, session_id=session_id)
            if record.status != "pending":
                raise PermissionError(f"Approval is not pending: {approval_id}")
            approved = ApprovalRecord(**{**asdict(record), "status": "approved"})
            self._records[approval_id] = approved
            self._save()
            return approved

    def reject(self, approval_id: str, *, session_id: str) -> ApprovalRecord:
        with self._lock:
            record = self._get_valid(approval_id, session_id=session_id)
            if record.status != "pending":
                raise PermissionError(f"Approval is not pending: {approval_id}")
            rejected = ApprovalRecord(**{**asdict(record), "status": "rejected"})
            self._records[approval_id] = rejected
            self._save()
            return rejected

    def consume(
        self,
        approval_id: str,
        *,
        session_id: str,
        operation: str,
        root: str,
        path: str,
        expected_sha256: str | None = None,
        destination_path: str | None = None,
    ) -> ApprovalRecord:
        with self._lock:
            record = self._get_valid(approval_id, session_id=session_id)
            if record.status != "approved":
                raise PermissionError("Approval has not been approved or was already consumed.")
            if (record.operation, record.root, record.path) != (operation, root, path):
                raise PermissionError("Approval scope does not match the requested operation.")
            if record.destination_path != destination_path:
                raise PermissionError("Approval destination scope does not match the requested operation.")
            if record.expected_sha256 != expected_sha256:
                raise PermissionError("Approval hash scope does not match the requested operation.")
            consumed = ApprovalRecord(**{**asdict(record), "status": "consumed"})
            self._records[approval_id] = consumed
            self._save()
            return consumed

    def _get_valid(self, approval_id: str, *, session_id: str) -> ApprovalRecord:
        record = self._records.get(approval_id)
        if record is None:
            raise KeyError(f"Unknown approval: {approval_id}")
        if record.session_id != session_id:
            raise PermissionError("Approval belongs to another session.")
        if record.expires_at <= time.time():
            raise PermissionError("Approval has expired.")
        return record

    def _load(self) -> None:
        if self.path is None or not self.path.exists():
            return
        data = json.loads(self.path.read_text(encoding="utf-8"))
        if not isinstance(data, list):
            raise RuntimeError("Approval store must contain a JSON list.")
        self._records = {
            item["approval_id"]: ApprovalRecord(**item)
            for item in data
            if isinstance(item, dict) and item.get("approval_id")
        }

    def _save(self) -> None:
        if self.path is None:
            return
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.path.write_text(
            json.dumps([asdict(record) for record in self._records.values()], indent=2) + "\n",
            encoding="utf-8",
        )


class AuditLog:
    def __init__(self, path: str | Path | None = None) -> None:
        self.path = Path(path) if path is not None else None
        self._lock = threading.Lock()

    def record(self, **event: Any) -> None:
        if self.path is None:
            return
        with self._lock:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            with self.path.open("a", encoding="utf-8") as stream:
                stream.write(json.dumps(event, ensure_ascii=False) + "\n")
