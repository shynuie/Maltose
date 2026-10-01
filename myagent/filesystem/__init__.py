"""Controlled local filesystem capabilities for MyAgent."""

from myagent.filesystem.paths import FilesystemRoot, PathResolver, ResolvedPath
from myagent.filesystem.policy import ApprovalRequired, PolicyDecision, PolicyEngine, WorkingRoot
from myagent.filesystem.approval import ApprovalManager, ApprovalRecord, AuditLog
from myagent.filesystem.config import FilesystemConfig
from myagent.filesystem.events import FilesystemMutationEvent, FilesystemMutationType
from myagent.filesystem.metrics import FilesystemRuntimeMetrics
from myagent.filesystem.ui import FilesystemApprovalUI
from myagent.filesystem.service import FileService

__all__ = [
    "FileService",
    "FilesystemConfig",
    "FilesystemMutationEvent",
    "FilesystemMutationType",
    "FilesystemRuntimeMetrics",
    "FilesystemRoot",
    "PathResolver",
    "ApprovalRequired",
    "ApprovalManager",
    "ApprovalRecord",
    "AuditLog",
    "FilesystemApprovalUI",
    "PolicyDecision",
    "PolicyEngine",
    "ResolvedPath",
    "WorkingRoot",
]
