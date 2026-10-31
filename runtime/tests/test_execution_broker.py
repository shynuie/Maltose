from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from myagent.execution.backend import BackendCapabilities, MountSpec
from myagent.execution.broker import ExecutionApprovalRequired, ExecutionBroker
from myagent.execution.models import ExecutionRequest, ExecutionResult, NetworkPolicy
from myagent.execution.policy import ExecutionPolicy
from myagent.filesystem.approval import ApprovalManager


class FakeBackend:
    def __init__(self) -> None:
        self.calls: list[tuple[ExecutionRequest, tuple[MountSpec, ...], Path]] = []

    @property
    def capabilities(self) -> BackendCapabilities:
        return BackendCapabilities(
            "fake", True, True, True, True, supports_restricted_network=True
        )

    def execute(self, request: ExecutionRequest, *, mounts: tuple[MountSpec, ...], session_dir: Path) -> ExecutionResult:
        self.calls.append((request, mounts, session_dir))
        self.assert_session(session_dir)
        return ExecutionResult("execution-1", "completed", 0, "ok", "")

    @staticmethod
    def assert_session(session_dir: Path) -> None:
        if not session_dir.is_dir():
            raise AssertionError("broker did not create a session directory")

    def close(self) -> None:
        pass


class ExecutionBrokerTests(unittest.TestCase):
    def test_broker_rejects_unscoped_mount_targets(self) -> None:
        backend = FakeBackend()
        broker = ExecutionBroker(backend)
        with tempfile.TemporaryDirectory() as directory:
            with self.assertRaises(PermissionError):
                broker.execute(
                    ExecutionRequest(("python",)),
                    mounts=(MountSpec(Path(directory).resolve(), "/etc", read_only=True),),
                )

    def test_broker_cleans_ephemeral_session_after_execution(self) -> None:
        backend = FakeBackend()
        broker = ExecutionBroker(backend)
        result = broker.execute(ExecutionRequest(("python",)))
        self.assertEqual(result.status, "completed")
        self.assertFalse(backend.calls[0][2].exists())

    def test_network_execution_is_scoped_to_one_approval(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            approvals = ApprovalManager(Path(directory) / "approvals.json")
            backend = FakeBackend()
            broker = ExecutionBroker(
                backend, ExecutionPolicy(), approval_manager=approvals, session_id="session-1"
            )
            request = ExecutionRequest(
                ("pip", "install", "pytest"),
                network=NetworkPolicy.RESTRICTED,
                allowed_domains=("pypi.org",),
            )
            with self.assertRaises(ExecutionApprovalRequired) as context:
                broker.execute(request)
            self.assertIsNotNone(context.exception.approval_id)
            approvals.approve(context.exception.approval_id, session_id="session-1")
            approved = ExecutionRequest(
                request.argv, profile=request.profile, network=request.network,
                allowed_domains=request.allowed_domains, approval_id=context.exception.approval_id,
            )
            broker.execute(approved)
            self.assertEqual(len(backend.calls), 1)


if __name__ == "__main__":
    unittest.main()
