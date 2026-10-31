"""Backend capability boundary for isolated command execution."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path, PurePosixPath
from typing import Protocol

from maltose.execution.models import ExecutionRequest, ExecutionResult


@dataclass(frozen=True)
class MountSpec:
    """A mount requested by the broker; backends must enforce its read-only bit."""

    source: Path
    target: str
    read_only: bool = True

    def __post_init__(self) -> None:
        if not self.source.is_absolute():
            raise ValueError("Backend mount source must be absolute.")
        if self.source.is_symlink():
            raise PermissionError("Backend mount source cannot be a symlink.")
        target = PurePosixPath(self.target)
        if (
            not self.target.startswith("/")
            or "\x00" in self.target
            or ".." in target.parts
            or "\\" in self.target
        ):
            raise ValueError("Backend mount target must be an absolute path without NUL bytes.")


@dataclass(frozen=True)
class BackendCapabilities:
    name: str
    supports_network_isolation: bool
    supports_read_only_mounts: bool
    supports_resource_limits: bool
    supports_process_tree_cleanup: bool
    supports_restricted_network: bool = False
    supports_disk_quota: bool = False


class SandboxBackend(Protocol):
    """Execution backend contract; implementations must be OS-enforced."""

    @property
    def capabilities(self) -> BackendCapabilities:
        ...

    def execute(
        self,
        request: ExecutionRequest,
        *,
        mounts: tuple[MountSpec, ...],
        session_dir: Path,
    ) -> ExecutionResult:
        """Execute only inside the backend's isolated environment."""
        ...

    def close(self) -> None:
        """Stop active processes and release backend resources."""
        ...
