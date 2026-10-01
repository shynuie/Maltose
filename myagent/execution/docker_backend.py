"""Docker-backed isolated execution backend.

The backend intentionally accepts only an argv list and explicit mounts. It
never invokes a host shell and fails closed when Docker is unavailable.
"""

from __future__ import annotations

import os
import signal
import shutil
import subprocess
import threading
import time
import uuid
from pathlib import Path

from myagent.execution.backend import BackendCapabilities, MountSpec
from myagent.execution.models import ExecutionRequest, ExecutionResult, NetworkPolicy


class SandboxBackendUnavailable(RuntimeError):
    """Raised when an isolated execution backend cannot be used."""


class DockerSandboxBackend:
    """Run commands in a disposable, non-privileged Docker container."""

    def __init__(self, *, image: str, docker_binary: str = "docker") -> None:
        if not image or any(character.isspace() for character in image) or "\x00" in image:
            raise ValueError("Docker image must be a non-empty token without whitespace.")
        self.image = image
        self.docker_binary = docker_binary
        self._resolved_binary: str | None = None
        self._storage_quota_supported = False

    @property
    def capabilities(self) -> BackendCapabilities:
        return BackendCapabilities(
            name="docker",
            supports_network_isolation=True,
            supports_read_only_mounts=True,
            supports_resource_limits=True,
            supports_process_tree_cleanup=True,
            supports_restricted_network=False,
            supports_disk_quota=self._storage_quota_supported,
        )

    def build_command(
        self,
        request: ExecutionRequest,
        *,
        mounts: tuple[MountSpec, ...],
        session_dir: Path,
    ) -> list[str]:
        if request.network is NetworkPolicy.RESTRICTED:
            raise SandboxBackendUnavailable(
                "Docker backend requires a network proxy for restricted allowlists."
            )
        network = "none" if request.network is NetworkPolicy.OFF else "bridge"
        if not session_dir.is_absolute():
            raise ValueError("Docker session directory must be absolute.")
        command = [
            self._resolved_binary or self.docker_binary, "run", "--rm", "--init",
            "--pull", "never",
            "--network", network,
            "--read-only",
            "--cap-drop", "ALL",
            "--security-opt", "no-new-privileges:true",
            "--pids-limit", str(request.limits.max_processes),
            "--memory", str(request.limits.memory_bytes),
            "--cpus", "1",
            "--workdir", "/execution",
            "--mount", f"type=bind,src={session_dir},dst=/execution",
            "--tmpfs", f"/tmp:rw,noexec,nosuid,nodev,size={request.limits.max_disk_bytes}",
            self.image,
            *request.argv,
        ]
        if self._storage_quota_supported:
            command[command.index(self.image):command.index(self.image)] = [
                "--storage-opt", f"size={request.limits.max_disk_bytes}",
            ]
        for mount in mounts:
            mode = ",readonly" if mount.read_only else ""
            command[command.index(self.image):command.index(self.image)] = [
                "--mount", f"type=bind,src={mount.source},dst={mount.target}{mode}",
            ]
        return command

    def execute(
        self,
        request: ExecutionRequest,
        *,
        mounts: tuple[MountSpec, ...],
        session_dir: Path,
    ) -> ExecutionResult:
        resolved_binary = shutil.which(self.docker_binary)
        if resolved_binary is None:
            raise SandboxBackendUnavailable("Docker executable is not installed.")
        self._resolved_binary = resolved_binary
        self._require_daemon()
        command = self.build_command(request, mounts=mounts, session_dir=session_dir)
        execution_id = uuid.uuid4().hex
        try:
            process = subprocess.Popen(
                command,
                stdin=subprocess.DEVNULL,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=False,
                start_new_session=True,
                env={},
            )
        except OSError as exc:
            raise SandboxBackendUnavailable(f"Could not start Docker backend: {exc}") from exc

        stdout, stderr, termination_status = _collect_output(
            process, request.limits.max_output_bytes, request.limits.timeout_seconds
        )
        return ExecutionResult(
            execution_id=execution_id,
            status=termination_status or ("completed" if process.returncode == 0 else "failed"),
            exit_code=process.returncode,
            stdout=stdout.decode("utf-8", errors="replace"),
            stderr=stderr.decode("utf-8", errors="replace"),
            approval_scope=request.approval_scope(),
        )

    def close(self) -> None:
        """Docker runs are disposable; active process cleanup is per execution."""

    def _require_daemon(self) -> None:
        try:
            completed = subprocess.run(
                [self._resolved_binary or self.docker_binary, "info"],
                stdin=subprocess.DEVNULL,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                timeout=3,
                check=False,
                text=True,
            )
        except (OSError, subprocess.SubprocessError) as exc:
            raise SandboxBackendUnavailable("Docker daemon preflight failed.") from exc
        if completed.returncode != 0:
            detail = (completed.stderr or "").strip()
            raise SandboxBackendUnavailable(
                f"Docker daemon is unavailable{': ' + detail if detail else '.'}"
            )
        driver = (completed.stdout or "").strip()
        self._storage_quota_supported = driver in {"devicemapper", "btrfs", "zfs"}


def _collect_output(
    process: subprocess.Popen[bytes],
    max_bytes: int,
    timeout_seconds: float,
) -> tuple[bytes, bytes, str | None]:
    buffers = [bytearray(), bytearray()]
    overflow = threading.Event()

    def read_stream(stream: object, index: int) -> None:
        if stream is None:
            return
        reader = stream  # type: ignore[assignment]
        while True:
            chunk = reader.read(8192)
            if not chunk:
                return
            remaining = max_bytes - len(buffers[index])
            if remaining <= 0:
                overflow.set()
                return
            buffers[index].extend(chunk[:remaining])
            if len(chunk) > remaining:
                overflow.set()
                return

    threads = [
        threading.Thread(target=read_stream, args=(process.stdout, 0), daemon=True),
        threading.Thread(target=read_stream, args=(process.stderr, 1), daemon=True),
    ]
    for thread in threads:
        thread.start()
    deadline = time.monotonic() + timeout_seconds
    termination_status: str | None = None
    while process.poll() is None:
        if overflow.is_set():
            termination_status = "output_limit_exceeded"
            _terminate_process_group(process)
            break
        if time.monotonic() >= deadline:
            termination_status = "timed_out"
            _terminate_process_group(process)
            break
        time.sleep(0.01)
    process.wait()
    for thread in threads:
        thread.join(timeout=1)
    for stream in (process.stdout, process.stderr):
        if stream is not None:
            stream.close()
    if termination_status == "output_limit_exceeded":
        buffers[1].extend(b"\n[output limit exceeded]\n")
    elif termination_status == "timed_out":
        buffers[1].extend(b"\n[execution timeout]\n")
    return bytes(buffers[0]), bytes(buffers[1]), termination_status


def _terminate_process_group(process: subprocess.Popen[bytes]) -> None:
    try:
        os.killpg(process.pid, signal.SIGKILL)
    except (OSError, ProcessLookupError):
        try:
            process.kill()
        except ProcessLookupError:
            pass
