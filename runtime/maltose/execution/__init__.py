"""Policy-first command execution interfaces.

The package currently defines the request/policy boundary only. Backends that
actually start processes must be added behind this interface and must never
fall back to an unrestricted host shell.
"""

from maltose.execution.models import (
    ExecutionLimits,
    ExecutionProfile,
    ExecutionRequest,
    ExecutionResult,
    NetworkPolicy,
    OutputArtifact,
)
from maltose.execution.backend import BackendCapabilities, MountSpec, SandboxBackend
from maltose.execution.docker_backend import DockerSandboxBackend, SandboxBackendUnavailable
from maltose.execution.broker import ExecutionApprovalRequired, ExecutionBroker
from maltose.execution.artifacts import ArtifactPromotionApprovalRequired, ArtifactPromoter, PromotionPlan
from maltose.execution.events import ExecutionEvent, ExecutionEventType, publish_to_event_hub
from maltose.execution.metrics import ExecutionRuntimeMetrics
from maltose.execution.tools import ExecutionToolAdapter
from maltose.execution.ui import ExecutionApprovalUI
from maltose.execution.policy import ExecutionPolicy, PolicyDecision

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
