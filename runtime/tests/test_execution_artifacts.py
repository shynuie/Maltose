from __future__ import annotations

import hashlib
import tempfile
import unittest
from pathlib import Path

from myagent.execution.artifacts import ArtifactPromotionApprovalRequired, ArtifactPromoter
from myagent.execution.models import OutputArtifact
from myagent.filesystem.approval import ApprovalManager
from myagent.filesystem.paths import FilesystemRoot, PathResolver
from myagent.filesystem.policy import PolicyEngine, WorkingRoot
from myagent.filesystem.service import FileService


class ArtifactPromotionTests(unittest.TestCase):
    def make_promoter(self, directory: str) -> tuple[Path, ArtifactPromoter, ApprovalManager]:
        base = Path(directory)
        workspace = base / "workspace"
        workspace.mkdir()
        resolver = PathResolver({
            "workspace": FilesystemRoot("workspace", workspace, read=True, write=True, delete=True),
        })
        approvals = ApprovalManager(base / "approvals.json")
        service = FileService(
            resolver, PolicyEngine(resolver, working_root=WorkingRoot("workspace")),
        )
        return workspace, ArtifactPromoter(
            service, approval_manager=approvals, session_id="session-1"
        ), approvals

    def test_plan_rejects_symlink_and_hash_mismatch(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            workspace, promoter, _ = self.make_promoter(directory)
            session = Path(directory) / "session"
            session.mkdir()
            output = session / "result.txt"
            output.write_text("result", encoding="utf-8")
            digest = hashlib.sha256(b"result").hexdigest()
            plan = promoter.plan(
                session,
                OutputArtifact("result.txt", "workspace", "result.txt", sha256=digest),
            )
            self.assertEqual(plan.size_bytes, 6)
            with self.assertRaises(RuntimeError):
                promoter.plan(
                    session,
                    OutputArtifact("result.txt", "workspace", "other.txt", sha256="0" * 64),
                )

    def test_promotion_requires_approval_then_writes_through_file_service(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            workspace, promoter, approvals = self.make_promoter(directory)
            session = Path(directory) / "session"
            session.mkdir()
            (session / "result.txt").write_text("result", encoding="utf-8")
            plan = promoter.plan(session, OutputArtifact("result.txt", "workspace", "result.txt"))
            with self.assertRaises(ArtifactPromotionApprovalRequired) as context:
                promoter.promote(plan)
            approvals.approve(context.exception.approval_id, session_id="session-1")
            result = promoter.promote(plan, approval_id=context.exception.approval_id)
            self.assertEqual(result["path"], "result.txt")
            self.assertEqual((workspace / "result.txt").read_text(encoding="utf-8"), "result")

    def test_batch_promotion_consumes_one_approval_for_multiple_outputs(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            workspace, promoter, approvals = self.make_promoter(directory)
            session = Path(directory) / "session"
            session.mkdir()
            (session / "a.txt").write_text("a", encoding="utf-8")
            (session / "b.txt").write_text("b", encoding="utf-8")
            plans = (
                promoter.plan(session, OutputArtifact("a.txt", "workspace", "a.txt")),
                promoter.plan(session, OutputArtifact("b.txt", "workspace", "b.txt")),
            )
            with self.assertRaises(ArtifactPromotionApprovalRequired) as context:
                promoter.promote_many(plans)
            approvals.approve(context.exception.approval_id, session_id="session-1")
            results = promoter.promote_many(plans, approval_id=context.exception.approval_id)
            self.assertEqual([result["path"] for result in results], ["a.txt", "b.txt"])
            self.assertEqual((workspace / "a.txt").read_text(), "a")
            self.assertEqual((workspace / "b.txt").read_text(), "b")


if __name__ == "__main__":
    unittest.main()
