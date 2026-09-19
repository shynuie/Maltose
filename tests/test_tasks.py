import tempfile
import time
import unittest
from pathlib import Path
from unittest.mock import patch

from myagent.agent import (
    CodexReadOnlyWorker,
    FunctionTaskWorker,
    TaskManager,
    TaskStatus,
    TaskStore,
)


class TaskManagerTest(unittest.TestCase):
    def test_runs_independent_tasks_and_persists_results(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            store = TaskStore(Path(tmpdir) / "tasks.sqlite3")
            manager = TaskManager(store, max_workers=2)
            manager.register_worker(
                "local",
                FunctionTaskWorker(lambda data: f"done: {data['name']}"),
            )
            records = manager.create_plan(
                [
                    {"task_id": "a", "title": "A", "worker_type": "local", "input": {"name": "A"}},
                    {"task_id": "b", "title": "B", "worker_type": "local", "input": {"name": "B"}},
                ],
                user_id="marvin",
            )

            deadline = time.time() + 2
            while time.time() < deadline:
                statuses = [manager.get_status(record.id)["status"] for record in records]
                if all(status == TaskStatus.SUCCEEDED for status in statuses):
                    break
                time.sleep(0.01)

            self.assertEqual(
                [manager.get_status(record.id)["result_summary"] for record in records],
                ["done: A", "done: B"],
            )
            self.assertEqual(store.list("marvin")[0].user_id, "marvin")
            manager.shutdown()
            store.close()

    @patch("myagent.agent.tasks.subprocess.run")
    def test_codex_worker_uses_read_only_sandbox(self, run) -> None:
        run.return_value.returncode = 0
        run.return_value.stdout = "stdout result"
        run.return_value.stderr = ""
        record = type("Record", (), {
            "title": "Inspect the repository",
            "input": {"prompt": "Find the test command."},
        })()
        progress = []

        result = CodexReadOnlyWorker(cwd=".").run(record, progress.append)

        self.assertEqual(result, "stdout result")
        self.assertEqual(progress, [5, 90])
        command = run.call_args.args[0]
        self.assertEqual(command[0:4], ["codex", "exec", "--sandbox", "read-only"])
        self.assertIn("--ephemeral", command)
        self.assertIn("--output-last-message", command)
        self.assertTrue(command[-1].startswith("Work in read-only mode."))

    def test_dependency_waits_then_runs_after_parent(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            store = TaskStore(Path(tmpdir) / "tasks.sqlite3")
            manager = TaskManager(store)
            manager.register_worker("local", FunctionTaskWorker(lambda _data: "ok"))
            manager.create_plan(
                [
                    {"task_id": "parent", "title": "Parent", "worker_type": "local"},
                    {
                        "task_id": "child",
                        "title": "Child",
                        "worker_type": "local",
                        "dependencies": ["parent"],
                    },
                ]
            )

            deadline = time.time() + 2
            while time.time() < deadline:
                if manager.get_status("child")["status"] == TaskStatus.SUCCEEDED:
                    break
                time.sleep(0.01)

            self.assertEqual(manager.get_status("parent")["status"], TaskStatus.SUCCEEDED)
            self.assertEqual(manager.get_status("child")["status"], TaskStatus.SUCCEEDED)
            manager.shutdown()
            store.close()

    def test_unknown_worker_fails_without_running_arbitrary_input(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            store = TaskStore(Path(tmpdir) / "tasks.sqlite3")
            manager = TaskManager(store)
            record = manager.create_plan(
                [{"title": "No shell", "worker_type": "shell", "input": {"command": "rm -rf /"}}]
            )[0]

            result = manager.get_status(record.id)
            self.assertEqual(result["status"], TaskStatus.FAILED)
            self.assertIn("No worker registered", result["error"])
            manager.shutdown()
            store.close()

    def test_cancel_and_retry(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            store = TaskStore(Path(tmpdir) / "tasks.sqlite3")
            manager = TaskManager(store)
            calls = 0

            def fail_once(_data):
                nonlocal calls
                calls += 1
                if calls == 1:
                    raise RuntimeError("temporary failure")
                return "recovered"

            manager.register_worker("local", FunctionTaskWorker(fail_once))
            record = manager.create_plan(
                [{"title": "Retry me", "worker_type": "local"}]
            )[0]
            deadline = time.time() + 2
            while time.time() < deadline and manager.get_status(record.id)["status"] == TaskStatus.RUNNING:
                time.sleep(0.01)
            self.assertEqual(manager.get_status(record.id)["status"], TaskStatus.FAILED)
            manager.retry(record.id)
            while time.time() < deadline:
                if manager.get_status(record.id)["status"] == TaskStatus.SUCCEEDED:
                    break
                time.sleep(0.01)
            self.assertEqual(manager.get_status(record.id)["result_summary"], "recovered")
            manager.shutdown()
            store.close()


if __name__ == "__main__":
    unittest.main()
