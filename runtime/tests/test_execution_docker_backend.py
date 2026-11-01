from __future__ import annotations

import tempfile
import subprocess
import unittest
from pathlib import Path
from unittest.mock import patch

from maltose.execution.docker_backend import (
    DockerSandboxBackend,
    SandboxBackendUnavailable,
    _storage_driver,
)
from maltose.execution.models import ExecutionRequest, NetworkPolicy
from maltose.execution.backend import MountSpec


class DockerBackendTests(unittest.TestCase):
    @patch('maltose.execution.docker_backend.subprocess.run')
    def test_cleanup_refuses_unknown_identity_and_never_removes_an_unscoped_container(self, run):
        backend = DockerSandboxBackend(image='python:3.12-slim')
        run.return_value = subprocess.CompletedProcess([],0,stdout='not-a-container-id',stderr='')
        with self.assertRaises(SandboxBackendUnavailable): backend._remove_owned_container('maltose-exec-fixture','fixture')
        self.assertEqual(run.call_count,1)
        command = run.call_args.args[0]
        self.assertIn('name=^/maltose-exec-fixture$',command)
        self.assertIn('label=dev.maltose.execution-id=fixture',command)
        self.assertNotIn('rm',command)

    @patch('maltose.execution.docker_backend.subprocess.run')
    def test_cleanup_error_never_claims_the_container_is_gone(self, run):
        backend = DockerSandboxBackend(image='python:3.12-slim')
        run.return_value = subprocess.CompletedProcess([],1,stdout='',stderr='engine unavailable')
        with self.assertRaises(SandboxBackendUnavailable): backend._remove_owned_container('maltose-exec-fixture','fixture')

    @patch('maltose.execution.docker_backend.subprocess.run')
    def test_cleanup_refuses_replacement_even_if_name_and_label_match(self, run):
        backend= DockerSandboxBackend(image='python:3.12-slim')
        run.return_value = subprocess.CompletedProcess([],0,stdout='d'*64,stderr='')
        with self.assertRaisesRegex(SandboxBackendUnavailable,'identity changed'):
            backend._remove_owned_container('maltose-exec-fixture','fixture',expected_identity='c'*64)
        self.assertEqual(run.call_count,1,'Changed IDs must never reach Docker rm')

    def test_native_creation_that_exhausts_budget_never_starts_container_work(self):
        from unittest.mock import Mock
        backend=DockerSandboxBackend(image='python:3.12-slim')
        lifetime=Mock();lifetime.create_docker.return_value='c'*64
        with tempfile.TemporaryDirectory() as directory, \
             patch('maltose.execution.docker_backend.shutil.which',return_value='/installed/docker'), \
             patch.object(backend,'_require_daemon'), \
             patch('maltose.runtime.lifetime.current_lifetime',return_value=lifetime), \
             patch('maltose.execution.docker_backend.time.monotonic',side_effect=[0,31]), \
             patch('maltose.execution.docker_backend.subprocess.Popen') as launch:
            result=backend.execute(ExecutionRequest(('python','--version')),mounts=(),session_dir=Path(directory))
        self.assertEqual(result.status,'timed_out');launch.assert_not_called()
        lifetime.cleanup_docker.assert_called_once_with(result.execution_id)

    def test_storage_driver_is_parsed_from_docker_info(self) -> None:
        info = "Containers: 3\nStorage Driver: btrfs\nDocker Root Dir: /var/lib/docker\n"
        self.assertEqual(_storage_driver(info), "btrfs")
        self.assertIsNone(_storage_driver("Storage Driver:\n"))

    def test_build_command_isolated_and_argv_only(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            backend = DockerSandboxBackend(image="python:3.12-slim")
            request = ExecutionRequest(("python", "-m", "pytest"))
            command = backend.build_command(
                request,
                mounts=(MountSpec(Path(directory).resolve(), "/inputs", read_only=True),),
                session_dir=Path(directory).resolve(),
            )

        self.assertIn("--network", command)
        self.assertIn("--pull", command)
        self.assertIn("never", command)
        self.assertIn("none", command)
        self.assertIn("--read-only", command)
        self.assertIn("--cap-drop", command)
        self.assertIn("ALL", command)
        self.assertIn("--security-opt", command)
        self.assertIn("no-new-privileges:true", command)
        self.assertEqual(command[-3:], ["python", "-m", "pytest"])
        self.assertNotIn("sh", command)

    def test_network_request_fails_closed(self) -> None:
        backend = DockerSandboxBackend(image="python:3.12-slim")
        request = ExecutionRequest(
            ("pip", "install", "pytest"),
            network=NetworkPolicy.RESTRICTED,
            allowed_domains=("pypi.org",),
        )
        with self.assertRaises(SandboxBackendUnavailable):
            backend.build_command(request, mounts=(), session_dir=Path("/tmp").resolve())

    def test_capabilities_advertise_missing_restricted_proxy(self) -> None:
        capabilities = DockerSandboxBackend(image="python:3.12-slim").capabilities
        self.assertTrue(capabilities.supports_network_isolation)
        self.assertFalse(capabilities.supports_restricted_network)

    def test_supported_storage_driver_adds_writable_layer_quota(self) -> None:
        backend = DockerSandboxBackend(image="python:3.12-slim")
        backend._storage_quota_supported = True
        command = backend.build_command(
            ExecutionRequest(("python", "--version")),
            mounts=(),
            session_dir=Path("/tmp").resolve(),
        )
        quota_index = command.index("--storage-opt")
        self.assertEqual(command[quota_index + 1], "size=536870912")

    def test_approved_network_uses_explicit_bridge_after_policy_approval(self) -> None:
        backend = DockerSandboxBackend(image="python:3.12-slim")
        request = ExecutionRequest(
            ("pip", "install", "pytest"),
            network=NetworkPolicy.APPROVED,
        )
        command = backend.build_command(request, mounts=(), session_dir=Path("/tmp").resolve())
        self.assertEqual(command[command.index("--network") + 1], "bridge")

    @patch("maltose.execution.docker_backend.shutil.which", return_value=None)
    def test_execute_requires_docker_binary(self, _which: object) -> None:
        backend = DockerSandboxBackend(image="python:3.12-slim")
        with tempfile.TemporaryDirectory() as directory:
            with self.assertRaises(SandboxBackendUnavailable):
                backend.execute(
                    ExecutionRequest(("python", "--version")),
                    mounts=(),
                    session_dir=Path(directory).resolve(),
                )

    @patch("maltose.execution.docker_backend.subprocess.run")
    @patch("maltose.execution.docker_backend.shutil.which", return_value="/usr/bin/docker")
    def test_execute_requires_running_docker_daemon(self, _which: object, run: object) -> None:
        run.return_value.returncode = 1
        run.return_value.stderr = "Cannot connect to the Docker daemon"
        backend = DockerSandboxBackend(image="python:3.12-slim")
        with tempfile.TemporaryDirectory() as directory:
            with self.assertRaises(SandboxBackendUnavailable):
                backend.execute(
                    ExecutionRequest(("python", "--version")),
                    mounts=(),
                    session_dir=Path(directory).resolve(),
                )

    @patch("maltose.execution.docker_backend.subprocess.run")
    @patch("maltose.execution.docker_backend.shutil.which", return_value="/usr/bin/docker")
    def test_daemon_preflight_enables_storage_quota_for_supported_driver(
        self, _which: object, run: object
    ) -> None:
        run.return_value.returncode = 0
        run.return_value.stdout = "Storage Driver: btrfs\n"
        run.return_value.stderr = ""
        backend = DockerSandboxBackend(image="python:3.12-slim")
        backend._resolved_binary = "/usr/bin/docker"
        backend._require_daemon()
        self.assertTrue(backend.capabilities.supports_disk_quota)


if __name__ == "__main__":
    unittest.main()
