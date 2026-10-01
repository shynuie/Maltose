"""Read-only filesystem service built on PathResolver and PolicyEngine."""

from __future__ import annotations

import hashlib
import json
import os
import re
import shutil
import tempfile
import time
import uuid
from pathlib import Path
from typing import Any

from myagent.filesystem.approval import ApprovalManager, AuditLog
from myagent.filesystem.events import FilesystemMutationEvent, FilesystemMutationType
from myagent.filesystem.paths import PathResolver, ResolvedPath
from myagent.filesystem.policy import ApprovalRequired, PolicyEngine


class FileService:
    """Perform bounded, policy-checked read operations."""

    def __init__(
        self,
        resolver: PathResolver,
        policy: PolicyEngine | None = None,
        *,
        approval_manager: ApprovalManager | None = None,
        audit_log: AuditLog | None = None,
        session_id: str = "default",
        trash_path: str | Path | None = None,
        approval_notifier: Any | None = None,
        mutation_observer: Any | None = None,
    ) -> None:
        self.resolver = resolver
        self.policy = policy or PolicyEngine(resolver)
        self.approval_manager = approval_manager
        self.audit_log = audit_log or AuditLog()
        self.session_id = session_id
        self.trash_path = Path(trash_path).expanduser().resolve() if trash_path else None
        self.approval_notifier = approval_notifier
        self.mutation_observer = mutation_observer

    def create_file(self, root: str, path: str, content: str) -> dict[str, Any]:
        resolved = self.resolver.resolve(root, path)
        self.policy.require_allowed(root, "create", target=resolved)
        if resolved.path.exists():
            raise FileExistsError(resolved.path)
        self._atomic_write(resolved, content.encode("utf-8"))
        self._emit(FilesystemMutationEvent(FilesystemMutationType.CREATED, root, resolved.path, resolved.relative_path))
        return self._write_result(resolved)

    def write_file(
        self,
        root: str,
        path: str,
        content: str,
        *,
        expected_sha256: str | None = None,
    ) -> dict[str, Any]:
        resolved = self.resolver.resolve(root, path)
        self.policy.require_allowed(root, "write", target=resolved)
        if resolved.path.exists() and expected_sha256 is None:
            raise ValueError("expected_sha256 is required when overwriting a file.")
        self._check_expected_hash(resolved, expected_sha256)
        self._atomic_write(resolved, content.encode("utf-8"))
        self._emit(FilesystemMutationEvent(FilesystemMutationType.MODIFIED, root, resolved.path, resolved.relative_path))
        return self._write_result(resolved)

    def replace_text(
        self,
        root: str,
        path: str,
        old_text: str,
        new_text: str,
        *,
        expected_sha256: str,
    ) -> dict[str, Any]:
        resolved = self.resolver.resolve(root, path, must_exist=True)
        self.policy.require_allowed(root, "patch", target=resolved)
        self._check_expected_hash(resolved, expected_sha256)
        current = resolved.path.read_text(encoding="utf-8")
        if current.count(old_text) != 1:
            raise ValueError("Patch text must match exactly once.")
        return self.write_file(
            root,
            path,
            current.replace(old_text, new_text, 1),
            expected_sha256=expected_sha256,
        )

    def copy_file(
        self,
        source_root: str,
        source_path: str,
        destination_root: str,
        destination_path: str,
    ) -> dict[str, Any]:
        source = self.resolver.resolve(source_root, source_path, must_exist=True)
        destination = self.resolver.resolve(destination_root, destination_path)
        if not source.path.is_file():
            raise IsADirectoryError(source.path)
        self.policy.require_allowed(
            destination_root, "copy", target=destination, source=source, destination=destination
        )
        if destination.path.exists():
            raise FileExistsError(destination.path)
        destination.path.parent.mkdir(parents=True, exist_ok=True)
        with tempfile.NamedTemporaryFile(
            dir=destination.path.parent, prefix=f".{destination.path.name}.", delete=False
        ) as temporary:
            temporary_path = temporary.name
        try:
            shutil.copy2(source.path, temporary_path)
            os.replace(temporary_path, destination.path)
        finally:
            Path(temporary_path).unlink(missing_ok=True)
        self._emit(FilesystemMutationEvent(
            FilesystemMutationType.COPIED, destination_root, destination.path,
            destination.relative_path, source_root=source_root, source_path=source.relative_path,
        ))
        return self._write_result(destination)

    def move_file(
        self,
        source_root: str,
        source_path: str,
        destination_root: str,
        destination_path: str,
        *,
        approval_id: str | None = None,
    ) -> dict[str, Any]:
        source = self.resolver.resolve(source_root, source_path, must_exist=True)
        destination = self.resolver.resolve(destination_root, destination_path)
        self.policy.require_allowed(
            destination_root, "move", target=destination, source=source, destination=destination
        )
        if not source.path.is_file():
            raise IsADirectoryError(source.path)
        if destination.path.exists():
            raise FileExistsError(destination.path)
        expected_sha256 = hashlib.sha256(source.path.read_bytes()).hexdigest()
        if self.approval_manager is None:
            raise ApprovalRequired("Move includes source deletion and requires approval.")
        if approval_id is None:
            record = self.approval_manager.create(
                session_id=self.session_id,
                operation="move",
                root=source_root,
                path=source.relative_path,
                destination_path=f"{destination_root}:{destination.relative_path}",
                expected_sha256=expected_sha256,
            )
            if self.approval_notifier is not None:
                self.approval_notifier(record)
            raise ApprovalRequired("Move includes source deletion and requires approval.", approval_id=record.approval_id)
        self.approval_manager.consume(
            approval_id,
            session_id=self.session_id,
            operation="move",
            root=source_root,
            path=source.relative_path,
            destination_path=f"{destination_root}:{destination.relative_path}",
            expected_sha256=expected_sha256,
        )
        self._check_expected_hash(source, expected_sha256)
        if destination.path.exists():
            raise FileExistsError(destination.path)
        destination.path.parent.mkdir(parents=True, exist_ok=True)
        os.replace(source.path, destination.path)
        result = self._write_result(destination)
        self.audit_log.record(
            timestamp=time.time(), session_id=self.session_id, operation="move",
            source_root=source_root, source_path=source.relative_path,
            destination_root=destination_root, destination_path=destination.relative_path,
            status="moved",
        )
        self._emit(FilesystemMutationEvent(
            FilesystemMutationType.MOVED, destination_root, destination.path,
            destination.relative_path, source_root=source_root, source_path=source.relative_path,
        ))
        return result

    def delete_file(
        self,
        root: str,
        path: str,
        *,
        expected_sha256: str | None = None,
        approval_id: str | None = None,
    ) -> dict[str, Any]:
        resolved = self.resolver.resolve(root, path, must_exist=True)
        if not resolved.path.is_file():
            raise IsADirectoryError(resolved.path)
        if expected_sha256 is None:
            expected_sha256 = hashlib.sha256(resolved.path.read_bytes()).hexdigest()
        decision = self.policy.evaluate(
            root, "delete", target=resolved, size_bytes=resolved.path.stat().st_size
        )
        if decision.action == "deny":
            raise PermissionError(decision.reason)
        if self.approval_manager is None:
            raise ApprovalRequired(decision.reason)
        if approval_id is None:
            record = self.approval_manager.create(
                session_id=self.session_id,
                operation="delete",
                root=root,
                path=resolved.relative_path,
                expected_sha256=expected_sha256,
            )
            if self.approval_notifier is not None:
                self.approval_notifier(record)
            raise ApprovalRequired(decision.reason, approval_id=record.approval_id)
        self.approval_manager.consume(
            approval_id,
            session_id=self.session_id,
            operation="delete",
            root=root,
            path=resolved.relative_path,
            expected_sha256=expected_sha256,
        )
        self._check_expected_hash(resolved, expected_sha256)
        if self.trash_path is None:
            raise RuntimeError("Trash path is not configured.")
        operation_id = uuid.uuid4().hex
        trash_target = self.trash_path / operation_id / resolved.root.name / resolved.relative_path
        trash_target.parent.mkdir(parents=True, exist_ok=False)
        shutil.move(str(resolved.path), str(trash_target))
        metadata = self.trash_path / operation_id / "metadata.json"
        metadata.write_text(
            json.dumps({
                "operation_id": operation_id,
                "session_id": self.session_id,
                "root": root,
                "path": resolved.relative_path,
                "sha256": expected_sha256,
            }, indent=2) + "\n",
            encoding="utf-8",
        )
        result = {
            "operation_id": operation_id,
            "root": root,
            "path": resolved.relative_path,
            "trash_path": str(trash_target),
            "status": "trashed",
        }
        self.audit_log.record(
            timestamp=time.time(), session_id=self.session_id, operation="delete", **result
        )
        self._emit(FilesystemMutationEvent(
            FilesystemMutationType.TRASHED, root, resolved.path, resolved.relative_path,
            operation_id=operation_id,
        ))
        return result

    def restore_file(self, operation_id: str) -> dict[str, Any]:
        if self.trash_path is None:
            raise RuntimeError("Trash path is not configured.")
        if not re.fullmatch(r"[0-9a-f]{32}", operation_id):
            raise PermissionError("Invalid trash operation ID.")
        metadata = self.trash_path / operation_id / "metadata.json"
        if not metadata.exists():
            raise KeyError(f"Unknown trash operation: {operation_id}")
        record = json.loads(metadata.read_text(encoding="utf-8"))
        if record.get("session_id") != self.session_id:
            raise PermissionError("Trash operation belongs to another session.")
        destination = self.resolver.resolve(record["root"], record["path"])
        self.policy.require_allowed(record["root"], "write", target=destination)
        if destination.path.exists():
            raise FileExistsError(destination.path)
        trash_source = self.trash_path / operation_id / record["root"] / destination.relative_path
        try:
            trash_source.resolve(strict=False).relative_to(self.trash_path)
        except ValueError as exc:
            raise PermissionError("Trash path escapes the configured trash directory.") from exc
        current = self.trash_path
        for component in trash_source.relative_to(self.trash_path).parts:
            current = current / component
            if current.is_symlink():
                raise PermissionError("Trash path contains a symlink component.")
        if trash_source.is_symlink():
            raise PermissionError("Trash source cannot be a symlink.")
        if not trash_source.is_file():
            raise FileNotFoundError(trash_source)
        destination.path.parent.mkdir(parents=True, exist_ok=True)
        shutil.move(str(trash_source), str(destination.path))
        result = {
            "operation_id": operation_id,
            "root": record["root"],
            "path": record["path"],
            "status": "restored",
        }
        self.audit_log.record(
            timestamp=time.time(), session_id=self.session_id, operation="restore", **result
        )
        self._emit(FilesystemMutationEvent(
            FilesystemMutationType.RESTORED, record["root"], destination.path,
            record["path"], operation_id=operation_id,
        ))
        return result

    def _emit(self, event: FilesystemMutationEvent) -> None:
        if self.mutation_observer is not None:
            self.mutation_observer(event)

    @staticmethod
    def _check_expected_hash(resolved: ResolvedPath, expected_sha256: str | None) -> None:
        if expected_sha256 is None:
            return
        if not resolved.path.exists():
            raise FileNotFoundError(resolved.path)
        actual = hashlib.sha256(resolved.path.read_bytes()).hexdigest()
        if actual != expected_sha256:
            raise RuntimeError("File changed since it was read; expected_sha256 does not match.")

    @staticmethod
    def _atomic_write(resolved: ResolvedPath, data: bytes) -> None:
        resolved.path.parent.mkdir(parents=True, exist_ok=True)
        with tempfile.NamedTemporaryFile(
            dir=resolved.path.parent, prefix=f".{resolved.path.name}.", delete=False
        ) as temporary:
            temporary.write(data)
            temporary.flush()
            os.fsync(temporary.fileno())
            temporary_path = temporary.name
        try:
            os.replace(temporary_path, resolved.path)
        finally:
            Path(temporary_path).unlink(missing_ok=True)

    @staticmethod
    def _write_result(resolved: ResolvedPath) -> dict[str, Any]:
        data = resolved.path.read_bytes()
        return {
            "root": resolved.root.name,
            "path": resolved.relative_path,
            "bytes": len(data),
            "sha256": hashlib.sha256(data).hexdigest(),
        }

    def read_file(self, root: str, path: str, *, max_bytes: int | None = None) -> dict[str, Any]:
        self.policy.require_allowed(root, "read")
        resolved = self.resolver.resolve(root, path, must_exist=True)
        if not resolved.path.is_file():
            raise IsADirectoryError(resolved.path)
        limit = max_bytes if max_bytes is not None else self.policy.max_read_bytes
        if limit <= 0 or limit > self.policy.max_read_bytes:
            raise ValueError("max_bytes must be positive and within the policy limit.")
        size = resolved.path.stat().st_size
        self.policy.require_allowed(root, "read", size_bytes=size)
        if size > limit:
            raise PermissionError("File exceeds the requested read limit.")
        data = resolved.path.read_bytes()
        if len(data) > limit:
            raise RuntimeError("File changed during read and exceeded the read limit.")
        return {
            "root": root,
            "path": resolved.relative_path,
            "bytes": len(data),
            "text": data.decode("utf-8"),
        }

    def list_files(
        self,
        root: str,
        path: str = ".",
        *,
        recursive: bool = False,
        limit: int = 100,
    ) -> list[dict[str, Any]]:
        if limit <= 0:
            raise ValueError("limit must be positive.")
        self.policy.require_allowed(root, "list", item_count=limit)
        base = self.resolver.resolve(root, path, must_exist=True)
        if not base.path.is_dir():
            raise NotADirectoryError(base.path)

        results: list[dict[str, Any]] = []
        pending = [base.path]
        while pending and len(results) < limit:
            current = pending.pop(0)
            children = sorted(current.iterdir(), key=lambda item: item.name)
            for child in children:
                relative = child.relative_to(base.root.path)
                checked = self.resolver.resolve(root, relative, must_exist=True)
                results.append(self._describe(checked))
                if recursive and child.is_dir():
                    pending.append(child)
                if len(results) >= limit:
                    break
        return results

    def search_files(
        self,
        root: str,
        query: str,
        path: str = ".",
        *,
        limit: int = 20,
        max_file_bytes: int | None = None,
    ) -> list[dict[str, Any]]:
        query = query.strip()
        if not query:
            raise ValueError("Search query cannot be empty.")
        if limit <= 0:
            raise ValueError("limit must be positive.")
        self.policy.require_allowed(root, "search", item_count=limit)
        base = self.resolver.resolve(root, path, must_exist=True)
        file_limit = max_file_bytes or self.policy.max_read_bytes
        if file_limit <= 0 or file_limit > self.policy.max_read_bytes:
            raise ValueError("max_file_bytes must be positive and within the policy limit.")

        candidates = [base] if base.path.is_file() else self._walk_files(root, base)
        results: list[dict[str, Any]] = []
        for candidate in candidates:
            if len(results) >= limit:
                break
            checked = candidate
            if checked.path.stat().st_size > file_limit:
                continue
            text = checked.path.read_text(encoding="utf-8")
            for line_number, line in enumerate(text.splitlines(), start=1):
                if query.casefold() in line.casefold():
                    results.append({
                        "root": root,
                        "path": checked.relative_path,
                        "line": line_number,
                        "text": line,
                    })
                    if len(results) >= limit:
                        break
        return results

    @staticmethod
    def _describe(resolved: ResolvedPath) -> dict[str, Any]:
        path = resolved.path
        return {
            "root": resolved.root.name,
            "path": resolved.relative_path,
            "type": "directory" if path.is_dir() else "file",
            "bytes": path.stat().st_size if path.is_file() else None,
        }

    def _walk_files(self, root: str, base: ResolvedPath) -> list[ResolvedPath]:
        files: list[ResolvedPath] = []
        pending = [base]
        while pending:
            current = pending.pop(0)
            for child in sorted(current.path.iterdir(), key=lambda item: item.name):
                relative = child.relative_to(base.root.path)
                checked = self.resolver.resolve(root, relative, must_exist=True)
                if checked.path.is_dir():
                    pending.append(checked)
                elif checked.path.is_file():
                    files.append(checked)
        return files
