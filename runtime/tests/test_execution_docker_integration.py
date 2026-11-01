from __future__ import annotations

import os
import subprocess
import time
import tempfile
import unittest
from pathlib import Path

from maltose.execution.backend import MountSpec
from maltose.execution.docker_backend import DockerSandboxBackend
from maltose.execution.models import ExecutionLimits, ExecutionRequest


@unittest.skipUnless(
    os.environ.get("MALTOSE_RUN_DOCKER_INTEGRATION", os.environ.get("MYAGENT_RUN_DOCKER_INTEGRATION")) == "1",
    "set MALTOSE_RUN_DOCKER_INTEGRATION=1 to run Docker integration tests",
)
class DockerIntegrationTests(unittest.TestCase):
    def test_network_off_container_can_write_only_to_workspace_mount(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            workspace = Path(directory) / "workspace"
            workspace.mkdir()
            backend = DockerSandboxBackend(image="python:3.12-slim")
            result = backend.execute(
                ExecutionRequest(
                    ("python", "-c", "from pathlib import Path; Path('/workspace/result.txt').write_text('ok')"),
                    limits=ExecutionLimits(max_disk_bytes=128 * 1024 * 1024),
                ),
                mounts=(MountSpec(workspace.resolve(), "/workspace", read_only=False),),
                session_dir=Path(directory).resolve(),
            )
            self.assertEqual(result.status, "completed", result.stderr)
            self.assertEqual((workspace / "result.txt").read_text(encoding="utf-8"), "ok")

    def test_read_only_mount_and_container_root_are_not_writable(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            readonly = Path(directory) / "readonly"
            readonly.mkdir()
            backend = DockerSandboxBackend(image="python:3.12-slim")
            result = backend.execute(
                ExecutionRequest(
                    ("python", "-c", "from pathlib import Path; Path('/inputs/blocked.txt').write_text('no')"),
                ),
                mounts=(MountSpec(readonly.resolve(), "/inputs", read_only=True),),
                session_dir=Path(directory).resolve(),
            )
            self.assertEqual(result.status, "failed")
            self.assertFalse((readonly / "blocked.txt").exists())

            root_result = backend.execute(
                ExecutionRequest(
                    ("python", "-c", "from pathlib import Path; Path('/blocked.txt').write_text('no')"),
                ),
                mounts=(),
                session_dir=Path(directory).resolve(),
            )
            self.assertEqual(root_result.status, "failed")

    def test_stdout_limit_is_enforced(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            backend = DockerSandboxBackend(image="python:3.12-slim")
            result = backend.execute(
                ExecutionRequest(
                    ("python", "-c", "print('x' * 1000000)"),
                    limits=ExecutionLimits(max_output_bytes=1024),
                ),
                mounts=(),
                session_dir=Path(directory).resolve(),
            )
            self.assertEqual(result.status, "output_limit_exceeded")

    def test_timeout_kills_container_process(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            backend = DockerSandboxBackend(image="python:3.12-slim")
            workspace = Path(directory) / 'workspace'; workspace.mkdir()
            unrelated = subprocess.run(['docker','run','--rm','--detach','--network','none','--read-only',
                '--cap-drop','ALL','--security-opt','no-new-privileges:true','--pull','never',
                'python:3.12-slim','python','-c','import time; time.sleep(300)'],
                check=True,stdout=subprocess.PIPE,stderr=subprocess.PIPE,text=True).stdout.strip()
            self.addCleanup(lambda: subprocess.run(['docker','container','rm','--force',unrelated],
                stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL,timeout=5))
            started = time.monotonic()
            result = backend.execute(
                ExecutionRequest(
                    ("python", "-c", "import signal,time,subprocess; from pathlib import Path; "
                     "signal.signal(signal.SIGTERM,signal.SIG_IGN); "
                     "subprocess.Popen(['python','-c','import signal,time; signal.signal(signal.SIGTERM,signal.SIG_IGN); time.sleep(300)']); "
                     "p=Path('/workspace/heartbeat');\nwhile True: p.write_text(str(time.monotonic())); time.sleep(.02)"),
                    limits=ExecutionLimits(timeout_seconds=1, max_output_bytes=1024),
                ),
                mounts=(MountSpec(workspace.resolve(), '/workspace', read_only=False),),
                session_dir=Path(directory).resolve(),
            )
            self.assertEqual(result.status, "timed_out")
            self.assertLess(time.monotonic() - started, 8)
            heartbeat = workspace / 'heartbeat'; self.assertTrue(heartbeat.exists())
            final = heartbeat.read_bytes(); time.sleep(.2)
            self.assertEqual(heartbeat.read_bytes(), final, 'Container or its child continued writing after timeout')
            remaining = subprocess.run(['docker','container','ls','--all','--filter',
                'label=dev.maltose.execution-id='+result.execution_id,'--format','{{.ID}}'],
                check=True,stdout=subprocess.PIPE,stderr=subprocess.PIPE,text=True)
            self.assertEqual(remaining.stdout.strip(),'')
            alive = subprocess.run(['docker','container','inspect','--format','{{.State.Running}}',unrelated],
                check=True,stdout=subprocess.PIPE,stderr=subprocess.PIPE,text=True)
            self.assertEqual(alive.stdout.strip(),'true','Cleanup must not stop unrelated containers')

    def test_pid_limit_stops_process_fanout(self) -> None:
        script = (
            "import os\n"
            "children=[]\n"
            "for _ in range(100):\n"
            "    try: pid=os.fork()\n"
            "    except OSError: print('fork-limited', len(children)); break\n"
            "    if pid == 0: os._exit(0)\n"
            "    children.append(pid)\n"
            "for pid in children: os.waitpid(pid, 0)"
        )
        with tempfile.TemporaryDirectory() as directory:
            backend = DockerSandboxBackend(image="python:3.12-slim")
            result = backend.execute(
                ExecutionRequest(
                    ("python", "-c", script),
                    limits=ExecutionLimits(
                        max_processes=8,
                        timeout_seconds=5,
                        max_output_bytes=1024,
                    ),
                ),
                mounts=(),
                session_dir=Path(directory).resolve(),
            )
            self.assertEqual(result.status, "completed", result.stderr)
            self.assertIn("fork-limited", result.stdout)


if __name__ == "__main__":
    unittest.main()
