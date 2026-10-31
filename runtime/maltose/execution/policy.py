"""Default-deny policy for command execution requests."""

from __future__ import annotations

from dataclasses import dataclass

from maltose.execution.models import ExecutionProfile, ExecutionRequest, NetworkPolicy


@dataclass(frozen=True)
class PolicyDecision:
    action: str
    reason: str

    @property
    def allowed(self) -> bool:
        return self.action == "allow"


class ExecutionPolicy:
    """Decide whether a request may reach an isolated backend.

    This policy is intentionally not a process sandbox. A backend must enforce
    the resulting mounts, limits and network settings at the OS/runtime layer.
    """

    def __init__(self, *, allow_privileged: bool = False) -> None:
        self.allow_privileged = allow_privileged

    def evaluate(self, request: ExecutionRequest) -> PolicyDecision:
        if request.profile is ExecutionProfile.PRIVILEGED and not self.allow_privileged:
            return PolicyDecision("deny", "Privileged execution is disabled by default.")
        if request.network is NetworkPolicy.APPROVED:
            return PolicyDecision("approval_required", "Network-enabled execution requires approval.")
        if request.network is NetworkPolicy.RESTRICTED:
            return PolicyDecision("approval_required", "Restricted network execution requires approval.")
        if request.profile is ExecutionProfile.WORKSPACE:
            return PolicyDecision("allow", "Workspace execution is allowed only in an isolated backend.")
        return PolicyDecision("allow", "Safe execution is allowed only in an isolated backend.")

    def require_allowed(self, request: ExecutionRequest) -> None:
        decision = self.evaluate(request)
        if decision.action == "approval_required":
            raise PermissionError(decision.reason)
        if not decision.allowed:
            raise PermissionError(decision.reason)
