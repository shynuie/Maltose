"""Serializable models for sandboxed command execution requests."""

from __future__ import annotations

import hashlib
import json
import re
from dataclasses import dataclass, field
from enum import StrEnum
from pathlib import PurePosixPath
from typing import Any


class ExecutionProfile(StrEnum):
    SAFE = "safe"
    WORKSPACE = "workspace"
    PRIVILEGED = "privileged"


class NetworkPolicy(StrEnum):
    OFF = "off"
    RESTRICTED = "restricted"
    APPROVED = "approved"


@dataclass(frozen=True)
class ExecutionLimits:
    timeout_seconds: float = 30.0
    memory_bytes: int = 256 * 1024 * 1024
    cpu_seconds: int = 30
    max_processes: int = 64
    max_disk_bytes: int = 512 * 1024 * 1024
    max_output_bytes: int = 4 * 1024 * 1024

    def __post_init__(self) -> None:
        if self.timeout_seconds <= 0 or self.cpu_seconds <= 0:
            raise ValueError("Execution time limits must be positive.")
        if any(value <= 0 for value in (
            self.memory_bytes, self.max_processes, self.max_disk_bytes, self.max_output_bytes
        )):
            raise ValueError("Execution resource limits must be positive.")


@dataclass(frozen=True)
class OutputArtifact:
    path: str
    destination_root: str | None = None
    destination_path: str | None = None
    sha256: str | None = None
    content_type: str | None = None

    def __post_init__(self) -> None:
        _validate_relative_path(self.path, field_name="output path")
        if (self.destination_root is None) != (self.destination_path is None):
            raise ValueError("Output destination root and path must be provided together.")
        if self.destination_path is not None:
            _validate_relative_path(self.destination_path, field_name="destination path")
        if self.sha256 is not None and not re.fullmatch(r"[0-9a-f]{64}", self.sha256):
            raise ValueError("Output artifact sha256 must be a lowercase hexadecimal digest.")
        if self.content_type is not None and (
            not re.fullmatch(r"[a-z0-9.+-]+/[a-z0-9.+*_-]+", self.content_type)
        ):
            raise ValueError("Output artifact content_type must be a MIME type.")


@dataclass(frozen=True)
class ExecutionRequest:
    argv: tuple[str, ...]
    profile: ExecutionProfile = ExecutionProfile.WORKSPACE
    network: NetworkPolicy = NetworkPolicy.OFF
    allowed_domains: tuple[str, ...] = ()
    input_paths: tuple[str, ...] = ()
    outputs: tuple[OutputArtifact, ...] = ()
    limits: ExecutionLimits = field(default_factory=ExecutionLimits)
    working_root: str = "workspace"
    approval_id: str | None = None

    def __post_init__(self) -> None:
        if not self.argv or any(not isinstance(item, str) or not item or "\x00" in item for item in self.argv):
            raise ValueError("Execution argv must contain at least one non-empty string without NUL bytes.")
        if any("\x00" in path for path in self.input_paths):
            raise ValueError("Execution input paths cannot contain NUL bytes.")
        for path in self.input_paths:
            _validate_relative_path(path, field_name="input path")
        if self.network is not NetworkPolicy.RESTRICTED and self.allowed_domains:
            raise ValueError("allowed_domains require restricted network policy.")
        for domain in self.allowed_domains:
            if not re.fullmatch(r"[A-Za-z0-9.-]+", domain) or domain.startswith(".") or domain.endswith("."):
                raise ValueError(f"Invalid exact network domain: {domain}")
        if self.network is NetworkPolicy.RESTRICTED and not self.allowed_domains:
            raise ValueError("Restricted network policy requires an exact domain allowlist.")

    def approval_scope(self) -> str:
        """Return a stable digest for one exact execution request."""
        payload: dict[str, Any] = {
            "argv": self.argv,
            "profile": self.profile.value,
            "network": self.network.value,
            "allowed_domains": self.allowed_domains,
            "input_paths": self.input_paths,
            "outputs": [artifact.__dict__ for artifact in self.outputs],
            "limits": self.limits.__dict__,
            "working_root": self.working_root,
        }
        encoded = json.dumps(payload, sort_keys=True, separators=(",", ":")).encode()
        return hashlib.sha256(encoded).hexdigest()


@dataclass(frozen=True)
class ExecutionResult:
    execution_id: str
    status: str
    exit_code: int | None
    stdout: str
    stderr: str
    output_paths: tuple[str, ...] = ()
    approval_scope: str | None = None


def _validate_relative_path(value: str, *, field_name: str) -> None:
    path = PurePosixPath(value)
    if not value or path.is_absolute() or ".." in path.parts or "\\" in value:
        raise ValueError(f"{field_name} must be a safe relative POSIX path.")
