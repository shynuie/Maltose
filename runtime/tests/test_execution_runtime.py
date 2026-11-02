from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from maltose.execution.backend import BackendCapabilities
from maltose.execution.broker import ExecutionBroker
from maltose.execution.events import ExecutionEventType
from maltose.execution.metrics import ExecutionRuntimeMetrics
from maltose.execution.models import ExecutionRequest, ExecutionResult
from maltose.filesystem.approval import AuditLog


class RuntimeBackend:
    @property
    def capabilities(self) -> BackendCapabilities:
        return BackendCapabilities("runtime-test", True, True, True, True)

    def execute(self, request: ExecutionRequest, *, mounts: tuple[object, ...], session_dir: Path) -> ExecutionResult:
        return ExecutionResult("backend-id", "completed", 0, "ok", "")

    def close(self) -> None:
        pass


class ExecutionRuntimeTests(unittest.TestCase):
    def test_broker_publishes_lifecycle_and_audits_result(self) -> None:
        events = []
        metrics = ExecutionRuntimeMetrics()
        with tempfile.TemporaryDirectory() as directory:
            audit = AuditLog(Path(directory) / "execution.jsonl")
            broker = ExecutionBroker(
                RuntimeBackend(), event_publisher=events.append,
                metrics=metrics, audit_log=audit,
            )
            result = broker.execute(ExecutionRequest(("python", "--version")))
            self.assertEqual(result.status, "completed")
            self.assertEqual(
                [event.type for event in events],
                [ExecutionEventType.QUEUED, ExecutionEventType.RUNNING, ExecutionEventType.COMPLETED],
            )
            self.assertEqual(len({event.execution_id for event in events}), 1)
            self.assertEqual(metrics.snapshot()["completed"], 1)
            self.assertIn('"status": "completed"', (Path(directory) / "execution.jsonl").read_text())


if __name__ == "__main__":
    unittest.main()
