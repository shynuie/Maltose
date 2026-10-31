from __future__ import annotations

import unittest
import tempfile
from unittest.mock import Mock

from myagent.execution.models import ExecutionProfile, ExecutionResult
from myagent.execution.tools import ExecutionToolAdapter


class ExecutionToolTests(unittest.TestCase):
    def test_tool_constructs_request_without_direct_subprocess(self) -> None:
        broker = Mock()
        broker.execute.return_value = ExecutionResult("id", "completed", 0, "ok", "")
        with tempfile.TemporaryDirectory() as directory:
            tool = ExecutionToolAdapter(broker, working_root=directory).tools()[0]
            result = tool.handler({"argv": ["python", "--version"]})
        broker.execute.assert_called_once()
        self.assertEqual(result["status"], "completed")
        self.assertEqual(broker.execute.call_args.args[0].argv, ("python", "--version"))

    def test_tool_rejects_malformed_argv(self) -> None:
        tool = ExecutionToolAdapter(Mock()).tools()[0]
        with self.assertRaises(ValueError):
            tool.handler({"argv": "python --version"})

    def test_tool_rejects_malformed_outputs(self) -> None:
        tool = ExecutionToolAdapter(Mock()).tools()[0]
        with self.assertRaises(ValueError):
            tool.handler({"argv": ["python"], "outputs": ["result.txt"]})

    def test_safe_profile_does_not_mount_working_root(self) -> None:
        broker = Mock()
        broker.execute.return_value = ExecutionResult("id", "completed", 0, "", "")
        with tempfile.TemporaryDirectory() as directory:
            tool = ExecutionToolAdapter(broker, working_root=directory).tools()[0]
            tool.handler({"argv": ["python"], "profile": ExecutionProfile.SAFE.value})
        self.assertEqual(broker.execute.call_args.kwargs["mounts"], ())

    def test_workspace_profile_mounts_readable_roots_read_only(self) -> None:
        broker = Mock()
        broker.execute.return_value = ExecutionResult("id", "completed", 0, "", "")
        with tempfile.TemporaryDirectory() as directory:
            tool = ExecutionToolAdapter(
                broker,
                working_root=directory,
                readable_roots=(("documents", directory),),
            ).tools()[0]
            tool.handler({"argv": ["python"], "input_paths": ["documents:."]})
        mounts = broker.execute.call_args.kwargs["mounts"]
        self.assertEqual([mount.target for mount in mounts], ["/workspace", "/inputs/documents"])
        self.assertTrue(mounts[1].read_only)

    def test_workspace_profile_does_not_mount_unrequested_readable_roots(self) -> None:
        broker = Mock()
        broker.execute.return_value = ExecutionResult("id", "completed", 0, "", "")
        with tempfile.TemporaryDirectory() as directory:
            tool = ExecutionToolAdapter(
                broker, working_root=directory, readable_roots=(("documents", directory),)
            ).tools()[0]
            tool.handler({"argv": ["python"]})
        self.assertEqual([mount.target for mount in broker.execute.call_args.kwargs["mounts"]], ["/workspace"])


if __name__ == "__main__":
    unittest.main()
