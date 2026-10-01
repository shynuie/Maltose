"""Policy-first command execution interfaces.

The package currently defines the request/policy boundary only. Backends that
actually start processes must be added behind this interface and must never
fall back to an unrestricted host shell.
"""

from myagent.execution.models import (
    ExecutionLimits,
    ExecutionProfile,
    ExecutionRequest,
    ExecutionResult,
    NetworkPolicy,
    OutputArtifact,
)
from myagent.execution.backend import BackendCapabilities, MountSpec, SandboxBackend
from myagent.execution.docker_backend import DockerSandboxBackend, SandboxBackendUnavailable
from myagent.execution.broker import ExecutionApprovalRequired, ExecutionBroker
from myagent.execution.artifacts import ArtifactPromotionApprovalRequired, ArtifactPromoter, PromotionPlan
from myagent.execution.events import ExecutionEvent, ExecutionEventType, publish_to_event_hub
from myagent.execution.metrics import ExecutionRuntimeMetrics
from myagent.execution.tools import ExecutionToolAdapter
from myagent.execution.ui import ExecutionApprovalUI
from myagent.execution.policy import ExecutionPolicy, PolicyDecision

__all__ = [
    "ExecutionLimits",
    "BackendCapabilities",
    "DockerSandboxBackend",
    "ExecutionApprovalRequired",
    "ExecutionBroker",
    "ExecutionEvent",
    "ExecutionEventType",
    "publish_to_event_hub",
    "ExecutionRuntimeMetrics",
    "ExecutionToolAdapter",
    "ExecutionApprovalUI",
    "ArtifactPromotionApprovalRequired",
    "ArtifactPromoter",
    "ExecutionPolicy",
    "ExecutionProfile",
    "ExecutionRequest",
    "ExecutionResult",
    "NetworkPolicy",
    "MountSpec",
    "OutputArtifact",
    "PolicyDecision",
    "SandboxBackend",
    "SandboxBackendUnavailable",
    "PromotionPlan",
]
