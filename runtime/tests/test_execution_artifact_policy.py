from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from myagent.execution.artifacts import ArtifactPromoter
from myagent.execution.models import OutputArtifact
from myagent.filesystem.paths import FilesystemRoot, PathResolver
from myagent.filesystem.policy import PolicyEngine, WorkingRoot
from myagent.filesystem.service import FileService


class ExecutionArtifactPolicyTests(unittest.TestCase):
    def make_promoter(self, directory: str, **kwargs: object) -> ArtifactPromoter:
        base = Path(directory)
        workspace = base / "workspace"
        workspace.mkdir()
        resolver = PathResolver({
            "workspace": FilesystemRoot("workspace", workspace, read=True, write=True, delete=True),
        })
        service = FileService(resolver, PolicyEngine(resolver, working_root=WorkingRoot("workspace")))
        return ArtifactPromoter(service, **kwargs)

    def test_total_quota_rejects_batch_before_promotion(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            promoter = self.make_promoter(directory, max_bytes=10, max_total_bytes=5)
            session = Path(directory) / "session"
            session.mkdir()
            (session / "a.txt").write_text("abc", encoding="utf-8")
            (session / "b.txt").write_text("def", encoding="utf-8")
            plans = (
                promoter.plan(session, OutputArtifact("a.txt", "workspace", "a.txt")),
                promoter.plan(session, OutputArtifact("b.txt", "workspace", "b.txt")),
            )
            with self.assertRaises(PermissionError):
                promoter.validate_plans(plans)

    def test_declared_content_type_must_match_known_extension(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            promoter = self.make_promoter(directory)
            session = Path(directory) / "session"
            session.mkdir()
            (session / "result.json").write_text("{}", encoding="utf-8")
            with self.assertRaises(RuntimeError):
                promoter.plan(
                    session,
                    OutputArtifact("result.json", "workspace", "result.json", content_type="text/plain"),
                )


if __name__ == "__main__":
    unittest.main()
