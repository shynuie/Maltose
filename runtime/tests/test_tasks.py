import tempfile
import threading
import time
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest.mock import patch

from maltose.agent import (
    AssistantMessageWorker,
    CodexReadOnlyWorker,
    FunctionTaskWorker,
    TaskManager,
    TaskStatus,
    TaskStore,
)


class TaskManagerTest(unittest.TestCase):
    def test_publishes_live_progress_for_running_task(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            store = TaskStore(Path(tmpdir) / "tasks.sqlite3")
            published = []
            manager = TaskManager(store, progress_publisher=published.append)
            manager.register_worker("local", FunctionTaskWorker(lambda _data: "done"))
            record = manager.create_plan(
                [{"title": "Live task", "worker_type": "local"}], user_id="marvin"
            )[0]

            deadline = time.time() + 2
            while time.time() < deadline:
                if manager.get_status(record.id)["status"] == TaskStatus.SUCCEEDED:
                    break
                time.sleep(0.01)

            self.assertGreaterEqual(len(published), 3)
            self.assertEqual({item["progress_id"] for item in published}, {record.id})
            self.assertEqual(published[-1]["status"], TaskStatus.SUCCEEDED)
            self.assertEqual(published[-1]["percent"], 100)
            manager.shutdown()
            store.close()

    def test_assistant_message_worker_returns_exact_message(self) -> None:
        record = type("Record", (), {"title": "fallback", "input": {"message": "你好！"}})()
        self.assertEqual(AssistantMessageWorker().run(record, lambda _progress: None), "你好！")

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
                    {"title": "A", "worker_type": "local", "input": {"name": "A"}},
                    {"title": "B", "worker_type": "local", "input": {"name": "B"}},
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

    def test_completion_notifications_are_scoped_and_consumed(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            store = TaskStore(Path(tmpdir) / "tasks.sqlite3")
            manager = TaskManager(store)
            manager.register_worker("local", FunctionTaskWorker(lambda _data: "done"))
            record = manager.create_plan(
                [{"title": "Notify me", "worker_type": "local"}],
                user_id="marvin",
            )[0]

            deadline = time.time() + 2
            while time.time() < deadline:
                if manager.get_status(record.id)["status"] == TaskStatus.SUCCEEDED:
                    break
                time.sleep(0.01)

            self.assertEqual(manager.drain_notifications("other"), [])
            notifications = manager.drain_notifications("marvin")
            self.assertEqual(notifications[0]["title"], "Notify me")
            self.assertEqual(
                [item["status"] for item in notifications],
                [TaskStatus.SUCCEEDED],
            )
            self.assertEqual(manager.drain_notifications("marvin"), [])
            manager.shutdown()
            store.close()

    def test_plan_size_is_bounded(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            store = TaskStore(Path(tmpdir) / "tasks.sqlite3")
            manager = TaskManager(store, max_tasks_per_plan=2)
            manager.register_worker("local", FunctionTaskWorker(lambda _data: "done"))
            with self.assertRaises(ValueError):
                manager.create_plan(
                    [
                        {"title": "one", "worker_type": "local"},
                        {"title": "two", "worker_type": "local"},
                        {"title": "three", "worker_type": "local"},
                    ]
                )
            manager.shutdown()
            store.close()

    def test_lists_only_active_tasks(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            store = TaskStore(Path(tmpdir) / "tasks.sqlite3")
            manager = TaskManager(store)
            manager.register_worker("slow", FunctionTaskWorker(lambda _data: "done"))
            active = store.create("Waiting", "slow", user_id="marvin")
            store.update(active.id, status=TaskStatus.WAITING)
            finished = store.create("Finished", "slow", user_id="marvin")
            store.update(finished.id, status=TaskStatus.SUCCEEDED, progress=100)

            result = manager.list_active_tasks("marvin")

            self.assertEqual([item["title"] for item in result], ["Waiting"])
            manager.shutdown()
            store.close()

    @patch("maltose.agent.tasks.subprocess.run")
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
            records = manager.create_plan(
                [
                    {"task_ref": "parent", "title": "Parent", "worker_type": "local"},
                    {
                        "task_ref": "child",
                        "title": "Child",
                        "worker_type": "local",
                        "dependencies": ["parent"],
                    },
                ]
            )

            deadline = time.time() + 2
            while time.time() < deadline:
                if manager.get_status(records[1].id)["status"] == TaskStatus.SUCCEEDED:
                    break
                time.sleep(0.01)

            self.assertEqual(manager.get_status(records[0].id)["status"], TaskStatus.SUCCEEDED)
            self.assertEqual(manager.get_status(records[1].id)["status"], TaskStatus.SUCCEEDED)
            manager.shutdown()
            store.close()

    def test_plan_ids_are_fresh_uuids_even_when_legacy_ids_are_reused(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            store = TaskStore(Path(tmpdir) / "tasks.sqlite3")
            manager = TaskManager(store)
            first = manager.create_plan(
                [{"task_id": "search_similar_papers", "title": "Search papers", "worker_type": "local"}]
            )[0]
            second = manager.create_plan(
                [{"task_id": "search_similar_papers", "title": "Search again", "worker_type": "local"}]
            )[0]

            self.assertNotEqual(first.id, second.id)
            self.assertRegex(first.id, r"^[0-9a-f-]{36}$")
            self.assertRegex(second.id, r"^[0-9a-f-]{36}$")
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

    def test_one_time_schedule_creates_and_runs_task(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            store = TaskStore(Path(tmpdir) / "tasks.sqlite3")
            manager = TaskManager(store)
            release = threading.Event()
            def worker(data):
                if not release.wait(5): raise TimeoutError("Fixture worker was not released")
                return data["result"]
            manager.register_worker("local", FunctionTaskWorker(worker))
            try:
                run_at = (datetime.now(timezone.utc) - timedelta(seconds=1)).isoformat()
                schedule = manager.create_schedule(
                    "Scheduled task", "local", run_at,
                    input={"result": "scheduled ok"}, user_id="marvin",
                )
                deadline = time.monotonic() + 2
                while time.monotonic() < deadline:
                    if store.get_schedule(schedule["schedule_id"]).status == "completed": break
                    time.sleep(0.02)
                self.assertEqual(store.get_schedule(schedule["schedule_id"]).status, "completed")
                # A one-time schedule is consumed when it dispatches, independently of
                # its worker. Waiting for that schedule never guaranteed a task result.
                task = manager.list_tasks("marvin")[0]
                self.assertEqual(task["status"], TaskStatus.RUNNING)
                self.assertIsNone(task["result_summary"])
                release.set()
                deadline = time.monotonic() + 2
                while time.monotonic() < deadline and manager.get_status(task["task_id"])["status"] == TaskStatus.RUNNING:
                    time.sleep(0.01)
                self.assertEqual(manager.get_status(task["task_id"])["status"], TaskStatus.SUCCEEDED)
                self.assertEqual(manager.get_status(task["task_id"])["result_summary"], "scheduled ok")
            finally:
                release.set(); manager.shutdown(); store.close()

    def test_recurring_schedule_can_be_paused_and_resumed(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            store = TaskStore(Path(tmpdir) / "tasks.sqlite3")
            manager = TaskManager(store)
            run_at = (datetime.now(timezone.utc) + timedelta(hours=1)).isoformat()
            schedule = manager.create_schedule(
                "Daily reminder", "local", run_at, recurrence="daily", user_id="marvin"
            )

            paused = manager.pause_schedule(schedule["schedule_id"], user_id="marvin")
            self.assertEqual(paused["status"], "paused")
            resumed = manager.resume_schedule(schedule["schedule_id"], user_id="marvin")
            self.assertEqual(resumed["status"], "active")
            cancelled = manager.cancel_schedule(schedule["schedule_id"], user_id="marvin")
            self.assertEqual(cancelled["status"], "cancelled")
            manager.shutdown()
            store.close()


if __name__ == "__main__":
    unittest.main()
