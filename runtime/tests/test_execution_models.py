from __future__ import annotations

import unittest

from maltose.execution.models import (
    ExecutionLimits,
    ExecutionProfile,
    ExecutionRequest,
    NetworkPolicy,
    OutputArtifact,
)
from maltose.execution.policy import ExecutionPolicy


class ExecutionModelTests(unittest.TestCase):
    def test_request_rejects_shell_path_escape_and_invalid_network_shape(self) -> None:
        with self.assertRaises(ValueError):
            ExecutionRequest(("python",), input_paths=("../secret.txt",))
        with self.assertRaises(ValueError):
            ExecutionRequest(("python",), network=NetworkPolicy.RESTRICTED)
        with self.assertRaises(ValueError):
            ExecutionRequest(("python",), network=NetworkPolicy.OFF, allowed_domains=("pypi.org",))

    def test_request_scope_is_stable_and_changes_with_destination(self) -> None:
        base = ExecutionRequest(
            ("python", "-m", "pytest"),
            outputs=(OutputArtifact("dist", "workspace", "dist"),),
        )
        same = ExecutionRequest(
            ("python", "-m", "pytest"),
            outputs=(OutputArtifact("dist", "workspace", "dist"),),
        )
        changed = ExecutionRequest(
            ("python", "-m", "pytest"),
            outputs=(OutputArtifact("build", "workspace", "build"),),
        )
        self.assertEqual(base.approval_scope(), same.approval_scope())
        self.assertNotEqual(base.approval_scope(), changed.approval_scope())

    def test_policy_defaults_to_isolated_workspace_and_denies_privileged(self) -> None:
        policy = ExecutionPolicy()
        workspace = ExecutionRequest(("pytest",))
        privileged = ExecutionRequest(("bash",), profile=ExecutionProfile.PRIVILEGED)
        self.assertTrue(policy.evaluate(workspace).allowed)
        self.assertEqual(policy.evaluate(privileged).action, "deny")

    def test_network_requires_approval(self) -> None:
        request = ExecutionRequest(
            ("pip", "install", "pytest"),
            network=NetworkPolicy.RESTRICTED,
            allowed_domains=("pypi.org", "files.pythonhosted.org"),
            limits=ExecutionLimits(timeout_seconds=60),
        )
        self.assertEqual(ExecutionPolicy().evaluate(request).action, "approval_required")


if __name__ == "__main__":
    unittest.main()
