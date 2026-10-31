"""Controlled local filesystem capabilities for Maltose."""

from maltose.filesystem.paths import FilesystemRoot, PathResolver, ResolvedPath
from maltose.filesystem.policy import ApprovalRequired, PolicyDecision, PolicyEngine, WorkingRoot
from maltose.filesystem.approval import ApprovalManager, ApprovalRecord, AuditLog
from maltose.filesystem.config import FilesystemConfig
from maltose.filesystem.events import FilesystemMutationEvent, FilesystemMutationType
from maltose.filesystem.metrics import FilesystemRuntimeMetrics
from maltose.filesystem.ui import FilesystemApprovalUI
from maltose.filesystem.service import FileService

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
