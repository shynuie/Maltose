from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from myagent.execution.artifacts import ArtifactPromoter, ArtifactPromotionApprovalRequired
from myagent.execution.backend import BackendCapabilities
from myagent.execution.broker import ExecutionBroker
from myagent.execution.models import ExecutionRequest, ExecutionResult, OutputArtifact
from myagent.filesystem.approval import ApprovalManager
from myagent.filesystem.paths import FilesystemRoot, PathResolver
from myagent.filesystem.policy import PolicyEngine, WorkingRoot
from myagent.filesystem.service import FileService


class PromotionBackend:
    @property
    def capabilities(self) -> BackendCapabilities:
        return BackendCapabilities("promotion-test", True, True, True, True)

    def execute(self, request: ExecutionRequest, *, mounts: tuple[object, ...], session_dir: Path) -> ExecutionResult:
        (session_dir / "result.txt").write_text("artifact", encoding="utf-8")
        return ExecutionResult("backend", "completed", 0, "", "")

    def close(self) -> None:
        pass


class PromotionLifecycleTests(unittest.TestCase):
    def test_pending_promotion_keeps_session_until_resume(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            base = Path(directory)
            workspace = base / "workspace"
            workspace.mkdir()
            resolver = PathResolver({
                "workspace": FilesystemRoot("workspace", workspace, read=True, write=True, delete=True),
            })
            approvals = ApprovalManager(base / "approvals.json")
            promoter = ArtifactPromoter(
                FileService(resolver, PolicyEngine(resolver, working_root=WorkingRoot("workspace"))),
                approval_manager=approvals, session_id="session-1",
            )
            events = []
            pending_store = base / "pending.json"
            broker = ExecutionBroker(
                PromotionBackend(), artifact_promoter=promoter, session_id="session-1",
                event_publisher=events.append,
                pending_store=pending_store,
            )
            request = ExecutionRequest(
                ("generate",),
                outputs=(OutputArtifact("result.txt", "workspace", "result.txt"),),
            )
            with self.assertRaises(ArtifactPromotionApprovalRequired) as context:
                broker.execute(request)
            self.assertIsNotNone(context.exception.approval_id)
            approval_id = context.exception.approval_id
            approvals.approve(approval_id, session_id="session-1")
            execution_id = events[0].execution_id
            restarted_broker = ExecutionBroker(
                PromotionBackend(), artifact_promoter=promoter, session_id="session-1",
                pending_store=pending_store,
            )
            result = restarted_broker.resume_promotion(execution_id, approval_id=approval_id)
            self.assertEqual(result["status"], "promoted")
            self.assertEqual((workspace / "result.txt").read_text(encoding="utf-8"), "artifact")

    def test_promotion_can_resume_by_approval_id(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            base = Path(directory)
            workspace = base / "workspace"
            workspace.mkdir()
            resolver = PathResolver({
                "workspace": FilesystemRoot("workspace", workspace, read=True, write=True, delete=True),
            })
            approvals = ApprovalManager(base / "approvals.json")
            promoter = ArtifactPromoter(
                FileService(resolver, PolicyEngine(resolver, working_root=WorkingRoot("workspace"))),
                approval_manager=approvals, session_id="session-1",
            )
            events = []
            broker = ExecutionBroker(
                PromotionBackend(), artifact_promoter=promoter, session_id="session-1",
                event_publisher=events.append, pending_store=base / "pending.json",
            )
            request = ExecutionRequest(
                ("generate",), outputs=(OutputArtifact("result.txt", "workspace", "result.txt"),)
            )
            with self.assertRaises(ArtifactPromotionApprovalRequired) as context:
                broker.execute(request)
            approval_id = context.exception.approval_id
            approvals.approve(approval_id, session_id="session-1")
            result = broker.resume_promotion_by_approval(approval_id)
            self.assertEqual(result["status"], "promoted")


if __name__ == "__main__":
    unittest.main()
