"""Policy decisions for controlled filesystem capabilities."""

from __future__ import annotations

from dataclasses import dataclass

from maltose.filesystem.paths import PathResolver, ResolvedPath


@dataclass(frozen=True)
class WorkingRoot:
    root: str
    path: str = "."


class ApprovalRequired(PermissionError):
    """Raised when an operation is valid but needs a user approval token."""

    def __init__(self, message: str, *, approval_id: str | None = None) -> None:
        super().__init__(message)
        self.approval_id = approval_id


@dataclass(frozen=True)
class PolicyDecision:
    action: str
    reason: str

    @property
    def allowed(self) -> bool:
        return self.action == "allow"


class PolicyEngine:
    """Apply root permissions and risk rules before filesystem I/O."""

    _READ_OPERATIONS = frozenset({"list", "read", "search"})
    _WRITE_OPERATIONS = frozenset({"create", "write", "patch", "copy", "move"})

    def __init__(
        self,
        resolver: PathResolver,
        *,
        max_read_bytes: int = 1_048_576,
        max_search_results: int = 100,
        working_root: WorkingRoot | None = None,
    ) -> None:
        if max_read_bytes <= 0 or max_search_results <= 0:
            raise ValueError("Filesystem policy limits must be positive.")
        self.resolver = resolver
        self.max_read_bytes = max_read_bytes
        self.max_search_results = max_search_results
        self.working_root = working_root

    def evaluate(
        self,
        root_name: str,
        operation: str,
        *,
        size_bytes: int = 0,
        item_count: int = 1,
        target: ResolvedPath | None = None,
        source: ResolvedPath | None = None,
        destination: ResolvedPath | None = None,
    ) -> PolicyDecision:
        if size_bytes < 0 or item_count < 1:
            return PolicyDecision("deny", "Invalid filesystem operation limits.")
        root = self.resolver.root(root_name)
        if operation in self._READ_OPERATIONS:
            if not root.read:
                return PolicyDecision("deny", f"Read access is disabled for root: {root_name}")
            if size_bytes > self.max_read_bytes:
                return PolicyDecision("deny", "Requested read exceeds the configured byte limit.")
            if item_count > self.max_search_results:
                return PolicyDecision("deny", "Requested result count exceeds the configured limit.")
            return PolicyDecision("allow", "Read operation is allowed.")

        if operation in self._WRITE_OPERATIONS:
            if target is None or not self._is_working_target(target):
                return PolicyDecision("deny", "Write target must be inside the session working root.")
            if operation in {"copy", "move"} and destination is not None:
                if not self._is_working_target(destination):
                    return PolicyDecision("deny", "Copy or move destination must be inside the working root.")
            if not root.write:
                return PolicyDecision("deny", f"Write access is disabled for root: {root_name}")
            if operation == "move":
                if source is None or not self._is_working_target(source):
                    return PolicyDecision("deny", "Move source must also be inside the working root.")
                if not source.root.write or not source.root.delete:
                    return PolicyDecision("deny", "Move source must allow write and delete access.")
            return PolicyDecision("allow", "Write operation is inside the working root.")

        if operation == "delete":
            if target is None or not self._is_working_target(target):
                return PolicyDecision("deny", "Delete target must be inside the session working root.")
            if not root.delete:
                return PolicyDecision("deny", f"Delete access is disabled for root: {root_name}")
            return PolicyDecision("approval_required", "Delete operations require explicit approval.")

        return PolicyDecision("deny", f"Unknown filesystem operation: {operation}")

    def require_allowed(self, root_name: str, operation: str, **kwargs: object) -> None:
        decision = self.evaluate(root_name, operation, **kwargs)
        if decision.action == "approval_required":
            raise ApprovalRequired(decision.reason)
        if not decision.allowed:
            raise PermissionError(decision.reason)

    def _is_working_target(self, target: ResolvedPath) -> bool:
        return (
            self.working_root is not None
            and self.resolver.is_within(
                target, self.working_root.root, self.working_root.path
            )
        )
