"""Durable local task orchestration primitives."""

from __future__ import annotations

import json
import logging
import sqlite3
import subprocess
import threading
import tempfile
import uuid
from concurrent.futures import Future, ThreadPoolExecutor
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Callable, Protocol
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

logger = logging.getLogger(__name__)


class TaskStatus:
    PENDING = "pending"
    RUNNING = "running"
    WAITING = "waiting"
    SUCCEEDED = "succeeded"
    FAILED = "failed"
    CANCELLED = "cancelled"


class ScheduleStatus:
    ACTIVE = "active"
    PAUSED = "paused"
    COMPLETED = "completed"
    CANCELLED = "cancelled"


TERMINAL_STATUSES = {
    TaskStatus.SUCCEEDED,
    TaskStatus.FAILED,
    TaskStatus.CANCELLED,
}


@dataclass(frozen=True)
class TaskRecord:
    id: str
    user_id: str
    title: str
    worker_type: str
    input: dict[str, Any]
    status: str
    progress: int
    result_summary: str | None
    error: str | None
    dependencies: tuple[str, ...]
    created_at: str
    updated_at: str

    @classmethod
    def from_row(cls, row: sqlite3.Row) -> "TaskRecord":
        return cls(
            id=row["id"],
            user_id=row["user_id"],
            title=row["title"],
            worker_type=row["worker_type"],
            input=json.loads(row["input_json"]),
            status=row["status"],
            progress=row["progress"],
            result_summary=row["result_summary"],
            error=row["error"],
            dependencies=tuple(json.loads(row["dependencies_json"])),
            created_at=row["created_at"],
            updated_at=row["updated_at"],
        )

    def as_dict(self) -> dict[str, Any]:
        return {
            "task_id": self.id,
            "user_id": self.user_id,
            "title": self.title,
            "worker_type": self.worker_type,
            "input": self.input,
            "status": self.status,
            "progress": self.progress,
            "result_summary": self.result_summary,
            "error": self.error,
            "dependencies": list(self.dependencies),
            "created_at": self.created_at,
            "updated_at": self.updated_at,
        }


@dataclass(frozen=True)
class ScheduleRecord:
    id: str
    user_id: str
    title: str
    worker_type: str
    input: dict[str, Any]
    run_at: str
    recurrence: str
    timezone: str
    status: str
    next_run_at: str | None
    last_run_at: str | None
    created_at: str
    updated_at: str
    error: str | None

    @classmethod
    def from_row(cls, row: sqlite3.Row) -> "ScheduleRecord":
        return cls(
            id=row["id"], user_id=row["user_id"], title=row["title"],
            worker_type=row["worker_type"], input=json.loads(row["input_json"]),
            run_at=row["run_at"], recurrence=row["recurrence"], timezone=row["timezone"],
            status=row["status"], next_run_at=row["next_run_at"],
            last_run_at=row["last_run_at"], created_at=row["created_at"],
            updated_at=row["updated_at"], error=row["error"],
        )

    def as_dict(self) -> dict[str, Any]:
        return {
            "schedule_id": self.id, "user_id": self.user_id, "title": self.title,
            "worker_type": self.worker_type, "input": self.input, "run_at": self.run_at,
            "recurrence": self.recurrence, "timezone": self.timezone, "status": self.status,
            "next_run_at": self.next_run_at, "last_run_at": self.last_run_at,
            "created_at": self.created_at, "updated_at": self.updated_at, "error": self.error,
        }


class TaskStore:
    """SQLite-backed task state store safe for worker threads."""

    def __init__(self, path: str | Path = "data/tasks/tasks.sqlite3") -> None:
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._lock = threading.RLock()
        self._connection = sqlite3.connect(
            self.path, check_same_thread=False, timeout=30
        )
        self._connection.row_factory = sqlite3.Row
        self._connection.execute("PRAGMA journal_mode=WAL")
        self._connection.execute("PRAGMA foreign_keys=ON")
        self._create_schema()

    def _create_schema(self) -> None:
        with self._lock, self._connection:
            self._connection.execute(
                """
                CREATE TABLE IF NOT EXISTS tasks (
                    id TEXT PRIMARY KEY,
                    user_id TEXT NOT NULL,
                    title TEXT NOT NULL,
                    worker_type TEXT NOT NULL,
                    input_json TEXT NOT NULL,
                    status TEXT NOT NULL,
                    progress INTEGER NOT NULL DEFAULT 0,
                    result_summary TEXT,
                    error TEXT,
                    dependencies_json TEXT NOT NULL DEFAULT '[]',
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL
                )
                """
            )
            self._connection.execute(
                "CREATE INDEX IF NOT EXISTS idx_tasks_user_updated "
                "ON tasks(user_id, updated_at DESC)"
            )
            self._connection.execute(
                """
                CREATE TABLE IF NOT EXISTS schedules (
                    id TEXT PRIMARY KEY,
                    user_id TEXT NOT NULL,
                    title TEXT NOT NULL,
                    worker_type TEXT NOT NULL,
                    input_json TEXT NOT NULL,
                    run_at TEXT NOT NULL,
                    recurrence TEXT NOT NULL,
                    timezone TEXT NOT NULL,
                    status TEXT NOT NULL,
                    next_run_at TEXT,
                    last_run_at TEXT,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL,
                    error TEXT
                )
                """
            )
            self._connection.execute(
                "CREATE INDEX IF NOT EXISTS idx_schedules_due "
                "ON schedules(status, next_run_at)"
            )

    def close(self) -> None:
        with self._lock:
            self._connection.close()

    def create(
        self,
        title: str,
        worker_type: str,
        input: dict[str, Any] | None = None,
        dependencies: list[str] | None = None,
        user_id: str = "default",
        task_id: str | None = None,
    ) -> TaskRecord:
        title = title.strip()
        if not title:
            raise ValueError("Task title cannot be empty.")
        now = _now()
        task_id = task_id or str(uuid.uuid4())
        with self._lock, self._connection:
            self._connection.execute(
                """
                INSERT INTO tasks (
                    id, user_id, title, worker_type, input_json, status,
                    progress, dependencies_json, created_at, updated_at
                ) VALUES (?, ?, ?, ?, ?, ?, 0, ?, ?, ?)
                """,
                (
                    task_id,
                    user_id,
                    title,
                    worker_type,
                    json.dumps(input or {}, ensure_ascii=False),
                    TaskStatus.PENDING,
                    json.dumps(dependencies or []),
                    now,
                    now,
                ),
            )
        return self.get(task_id)

    def get(self, task_id: str, user_id: str | None = None) -> TaskRecord:
        with self._lock:
            row = self._connection.execute(
                "SELECT * FROM tasks WHERE id = ?"
                + (" AND user_id = ?" if user_id is not None else ""),
                (task_id, user_id) if user_id is not None else (task_id,),
            ).fetchone()
        if row is None:
            raise KeyError(f"Unknown task: {task_id}")
        return TaskRecord.from_row(row)

    def list(self, user_id: str = "default", limit: int = 20) -> list[TaskRecord]:
        if limit < 1:
            raise ValueError("Task limit must be positive.")
        with self._lock:
            rows = self._connection.execute(
                "SELECT * FROM tasks WHERE user_id = ? "
                "ORDER BY updated_at DESC LIMIT ?",
                (user_id, limit),
            ).fetchall()
        return [TaskRecord.from_row(row) for row in rows]

    def update(
        self,
        task_id: str,
        *,
        status: str | None = None,
        progress: int | None = None,
        result_summary: str | None = None,
        error: str | None = None,
    ) -> TaskRecord:
        values: list[Any] = []
        updates: list[str] = []
        if status is not None:
            updates.append("status = ?")
            values.append(status)
        if progress is not None:
            if not 0 <= progress <= 100:
                raise ValueError("Task progress must be between 0 and 100.")
            updates.append("progress = ?")
            values.append(progress)
        if result_summary is not None:
            updates.append("result_summary = ?")
            values.append(result_summary)
        if error is not None:
            updates.append("error = ?")
            values.append(error)
        if not updates:
            return self.get(task_id)
        updates.append("updated_at = ?")
        values.append(_now())
        values.append(task_id)
        with self._lock, self._connection:
            cursor = self._connection.execute(
                f"UPDATE tasks SET {', '.join(updates)} WHERE id = ?", values
            )
            if cursor.rowcount == 0:
                raise KeyError(f"Unknown task: {task_id}")
        return self.get(task_id)

    def dependencies(self, task_id: str) -> list[TaskRecord]:
        task = self.get(task_id)
        return [self.get(dep_id) for dep_id in task.dependencies]

    def create_schedule(
        self,
        title: str,
        worker_type: str,
        run_at: str,
        *,
        recurrence: str = "once",
        timezone_name: str = "UTC",
        input: dict[str, Any] | None = None,
        user_id: str = "default",
        schedule_id: str | None = None,
    ) -> ScheduleRecord:
        title = title.strip()
        if not title:
            raise ValueError("Schedule title cannot be empty.")
        if recurrence not in {"once", "daily", "weekly"}:
            raise ValueError("Schedule recurrence must be once, daily, or weekly.")
        normalized_run_at = _parse_schedule_time(run_at, timezone_name).isoformat()
        schedule_id = schedule_id or str(uuid.uuid4())
        now = _now()
        with self._lock, self._connection:
            self._connection.execute(
                """INSERT INTO schedules (
                    id, user_id, title, worker_type, input_json, run_at, recurrence,
                    timezone, status, next_run_at, created_at, updated_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                (
                    schedule_id, user_id, title, worker_type,
                    json.dumps(input or {}, ensure_ascii=False), normalized_run_at, recurrence,
                    timezone_name, ScheduleStatus.ACTIVE, normalized_run_at, now, now,
                ),
            )
        return self.get_schedule(schedule_id)

    def get_schedule(self, schedule_id: str, user_id: str | None = None) -> ScheduleRecord:
        with self._lock:
            row = self._connection.execute(
                "SELECT * FROM schedules WHERE id = ?"
                + (" AND user_id = ?" if user_id is not None else ""),
                (schedule_id, user_id) if user_id is not None else (schedule_id,),
            ).fetchone()
        if row is None:
            raise KeyError(f"Unknown schedule: {schedule_id}")
        return ScheduleRecord.from_row(row)

    def list_schedules(self, user_id: str = "default", limit: int = 20) -> list[ScheduleRecord]:
        if limit < 1:
            raise ValueError("Schedule limit must be positive.")
        with self._lock:
            rows = self._connection.execute(
                "SELECT * FROM schedules WHERE user_id = ? ORDER BY updated_at DESC LIMIT ?",
                (user_id, limit),
            ).fetchall()
        return [ScheduleRecord.from_row(row) for row in rows]

    def due_schedules(self, now: str | None = None) -> list[ScheduleRecord]:
        now = now or _now()
        with self._lock:
            rows = self._connection.execute(
                "SELECT * FROM schedules WHERE status = ? AND next_run_at <= ? ORDER BY next_run_at",
                (ScheduleStatus.ACTIVE, now),
            ).fetchall()
        return [ScheduleRecord.from_row(row) for row in rows]

    def update_schedule(self, schedule_id: str, **fields: Any) -> ScheduleRecord:
        allowed = {"status", "next_run_at", "last_run_at", "error"}
        unknown = set(fields) - allowed
        if unknown:
            raise ValueError(f"Unsupported schedule fields: {sorted(unknown)}")
        updates = [(key, value) for key, value in fields.items()]
        if not updates:
            return self.get_schedule(schedule_id)
        updates.append(("updated_at", _now()))
        values = [value for _, value in updates] + [schedule_id]
        with self._lock, self._connection:
            cursor = self._connection.execute(
                f"UPDATE schedules SET {', '.join(f'{key} = ?' for key, _ in updates)} WHERE id = ?",
                values,
            )
            if cursor.rowcount == 0:
                raise KeyError(f"Unknown schedule: {schedule_id}")
        return self.get_schedule(schedule_id)


class TaskWorker(Protocol):
    def run(
        self, task: TaskRecord, report_progress: Callable[[int], None]
    ) -> str:
        ...


class FunctionTaskWorker:
    """Adapter for deterministic local workers and tests."""

    def __init__(self, function: Callable[[dict[str, Any]], str]) -> None:
        self.function = function

    def run(
        self, task: TaskRecord, report_progress: Callable[[int], None]
    ) -> str:
        report_progress(10)
        result = self.function(task.input)
        report_progress(100)
        return str(result)


class AssistantMessageWorker:
    """Turn a scheduled message into a normal task notification."""

    def run(
        self, task: TaskRecord, report_progress: Callable[[int], None]
    ) -> str:
        message = task.input.get("message") or task.input.get("text") or task.title
        if not isinstance(message, str) or not message.strip():
            raise ValueError("assistant_message requires input.message or input.text.")
        report_progress(100)
        return message.strip()


class CodexReadOnlyWorker:
    """Run a bounded Codex task with the read-only sandbox policy."""

    def __init__(
        self,
        cwd: str | Path = ".",
        *,
        executable: str = "codex",
        timeout: float = 300.0,
        max_output_chars: int = 12000,
    ) -> None:
        if timeout <= 0:
            raise ValueError("Codex timeout must be positive.")
        if max_output_chars < 1:
            raise ValueError("Codex output limit must be positive.")
        self.cwd = str(Path(cwd).resolve())
        self.executable = executable
        self.timeout = timeout
        self.max_output_chars = max_output_chars

    def run(
        self, task: TaskRecord, report_progress: Callable[[int], None]
    ) -> str:
        prompt = task.input.get("prompt")
        if not isinstance(prompt, str) or not prompt.strip():
            prompt = task.title
        prompt = (
            "Work in read-only mode. Do not modify files, run destructive commands, "
            "or create side effects. Return a concise result for the parent agent.\n\n"
            + prompt.strip()
        )
        report_progress(5)
        with tempfile.TemporaryDirectory(prefix="myagent-codex-") as temp_dir:
            output_path = Path(temp_dir) / "last-message.txt"
            command = [
                self.executable,
                "exec",
                "--sandbox",
                "read-only",
                "--cd",
                self.cwd,
                "--ephemeral",
                "--output-last-message",
                str(output_path),
                prompt,
            ]
            try:
                completed = subprocess.run(
                    command,
                    capture_output=True,
                    text=True,
                    check=False,
                    timeout=self.timeout,
                )
            except subprocess.TimeoutExpired as exc:
                raise RuntimeError(
                    f"Codex task timed out after {self.timeout:.1f}s."
                ) from exc
            except OSError as exc:
                raise RuntimeError(f"Could not start Codex CLI: {exc}") from exc

            if completed.returncode != 0:
                detail = (completed.stderr or completed.stdout).strip()
                raise RuntimeError(
                    f"Codex exited with status {completed.returncode}: "
                    f"{detail[-self.max_output_chars:]}"
                )
            report_progress(90)
            if output_path.exists():
                result = output_path.read_text(encoding="utf-8").strip()
            else:
                result = completed.stdout.strip()
            if not result:
                raise RuntimeError("Codex returned an empty result.")
            return result[-self.max_output_chars:]


class TaskManager:
    """Bounded executor for independent tasks with durable state."""

    def __init__(
        self,
        store: TaskStore,
        *,
        max_workers: int = 2,
        max_tasks_per_plan: int = 8,
        workers: dict[str, TaskWorker] | None = None,
        progress_publisher: Callable[[dict[str, Any]], None] | None = None,
    ) -> None:
        if max_workers < 1:
            raise ValueError("max_workers must be positive.")
        if max_tasks_per_plan < 1:
            raise ValueError("max_tasks_per_plan must be positive.")
        self.store = store
        self.max_tasks_per_plan = max_tasks_per_plan
        self._workers = workers or {}
        self._progress_publisher = progress_publisher
        self._executor = ThreadPoolExecutor(
            max_workers=max_workers, thread_name_prefix="myagent-task"
        )
        self._futures: dict[str, Future[None]] = {}
        self._notifications: list[dict[str, Any]] = []
        self._progress_marks: dict[str, int] = {}
        self._lock = threading.RLock()
        self._stop_scheduler = threading.Event()
        self._scheduler = threading.Thread(
            target=self._schedule_loop, name="myagent-scheduler", daemon=True
        )
        self._scheduler.start()

    def register_worker(self, worker_type: str, worker: TaskWorker) -> None:
        if not worker_type or worker_type in self._workers:
            raise ValueError(f"Invalid or duplicate worker type: {worker_type!r}")
        self._workers[worker_type] = worker

    def create_schedule(
        self, title: str, worker_type: str, run_at: str, *,
        recurrence: str = "once", timezone_name: str = "UTC",
        input: dict[str, Any] | None = None, user_id: str = "default",
    ) -> dict[str, Any]:
        return self.store.create_schedule(
            title, worker_type, run_at, recurrence=recurrence,
            timezone_name=timezone_name, input=input, user_id=user_id,
        ).as_dict()

    def list_schedules(self, user_id: str = "default", limit: int = 20) -> list[dict[str, Any]]:
        return [item.as_dict() for item in self.store.list_schedules(user_id, limit)]

    def pause_schedule(self, schedule_id: str, user_id: str | None = None) -> dict[str, Any]:
        schedule = self.store.get_schedule(schedule_id, user_id=user_id)
        if schedule.status == ScheduleStatus.ACTIVE:
            schedule = self.store.update_schedule(schedule_id, status=ScheduleStatus.PAUSED)
        return schedule.as_dict()

    def resume_schedule(self, schedule_id: str, user_id: str | None = None) -> dict[str, Any]:
        schedule = self.store.get_schedule(schedule_id, user_id=user_id)
        if schedule.status == ScheduleStatus.PAUSED:
            schedule = self.store.update_schedule(schedule_id, status=ScheduleStatus.ACTIVE)
        return schedule.as_dict()

    def cancel_schedule(self, schedule_id: str, user_id: str | None = None) -> dict[str, Any]:
        schedule = self.store.get_schedule(schedule_id, user_id=user_id)
        if schedule.status not in {ScheduleStatus.COMPLETED, ScheduleStatus.CANCELLED}:
            schedule = self.store.update_schedule(schedule_id, status=ScheduleStatus.CANCELLED)
        return schedule.as_dict()

    def _schedule_loop(self) -> None:
        while not self._stop_scheduler.wait(0.5):
            try:
                for schedule in self.store.due_schedules():
                    self._run_schedule(schedule)
            except Exception:
                logger.exception("schedule_poll_failed")

    def _run_schedule(self, schedule: ScheduleRecord) -> None:
        now = schedule.next_run_at or _now()
        try:
            self.create_plan(
                [{"title": schedule.title, "worker_type": schedule.worker_type, "input": schedule.input}],
                user_id=schedule.user_id,
            )
            if schedule.recurrence == "once":
                self.store.update_schedule(
                    schedule.id, status=ScheduleStatus.COMPLETED, last_run_at=now, next_run_at=None
                )
            else:
                next_run = _next_schedule_time(now, schedule.recurrence, schedule.timezone)
                self.store.update_schedule(schedule.id, last_run_at=now, next_run_at=next_run)
        except Exception as exc:
            self.store.update_schedule(schedule.id, error=str(exc), last_run_at=now)
            logger.exception("schedule_run_failed schedule_id=%s", schedule.id)

    @property
    def worker_types(self) -> tuple[str, ...]:
        return tuple(self._workers)

    def create_plan(
        self, tasks: list[dict[str, Any]], *, user_id: str = "default"
    ) -> list[TaskRecord]:
        if not tasks:
            raise ValueError("Task plan cannot be empty.")
        if len(tasks) > self.max_tasks_per_plan:
            raise ValueError(
                f"Task plan cannot contain more than {self.max_tasks_per_plan} tasks."
            )
        task_ids: set[str] = set()
        for item in tasks:
            task_id = item.get("task_id")
            if task_id and task_id in task_ids:
                raise ValueError(f"Duplicate task_id in plan: {task_id}")
            if task_id:
                task_ids.add(task_id)
        records = []
        for item in tasks:
            dependencies = item.get("dependencies", [])
            if not isinstance(dependencies, list):
                raise ValueError("Task dependencies must be a list.")
            records.append(
                self.store.create(
                    title=str(item.get("title", "")),
                    worker_type=str(item.get("worker_type", "local")),
                    input=item.get("input", {}),
                    dependencies=dependencies,
                    user_id=user_id,
                    task_id=item.get("task_id"),
                )
            )
        for record in records:
            self._schedule_if_ready(record.id)
        return records

    def _schedule_if_ready(self, task_id: str) -> None:
        with self._lock:
            task = self.store.get(task_id)
            if task.status != TaskStatus.PENDING:
                return
            dependencies = self.store.dependencies(task_id)
            if any(dep.status in {TaskStatus.PENDING, TaskStatus.RUNNING, TaskStatus.WAITING} for dep in dependencies):
                self.store.update(task_id, status=TaskStatus.WAITING)
                return
            if any(dep.status in {TaskStatus.FAILED, TaskStatus.CANCELLED} for dep in dependencies):
                failed = self.store.update(
                    task_id,
                    status=TaskStatus.FAILED,
                    error="A dependency failed or was cancelled.",
                )
                self._queue_notification(failed)
                return
            worker = self._workers.get(task.worker_type)
            if worker is None:
                failed = self.store.update(
                    task_id,
                    status=TaskStatus.FAILED,
                    error=f"No worker registered for type: {task.worker_type}",
                )
                self._queue_notification(failed)
                return
            running = self.store.update(task_id, status=TaskStatus.RUNNING, progress=1)
            self._publish_progress(running)
            self._progress_marks[task_id] = 0
            self._futures[task_id] = self._executor.submit(self._run, task_id, worker)

    def _run(self, task_id: str, worker: TaskWorker) -> None:
        try:
            task = self.store.get(task_id)
            result = worker.run(task, lambda progress: self._report_progress(task_id, progress))
            completed = self.store.update(
                task_id, status=TaskStatus.SUCCEEDED, progress=100, result_summary=result
            )
            self._publish_progress(completed)
            self._queue_notification(completed)
        except Exception as exc:
            logger.exception("task_failed task_id=%s", task_id)
            failed = self.store.update(task_id, status=TaskStatus.FAILED, error=str(exc))
            self._publish_progress(failed)
            self._queue_notification(failed)
        finally:
            with self._lock:
                self._futures.pop(task_id, None)
                self._progress_marks.pop(task_id, None)
            self._schedule_dependents(task_id)

    def _report_progress(self, task_id: str, progress: int) -> None:
        updated = self.store.update(task_id, progress=progress)
        self._publish_progress(updated)
        if progress >= 100:
            return
        mark = min((progress // 25) * 25, 75)
        with self._lock:
            last_mark = self._progress_marks.get(task_id, 0)
            if mark >= 25 and mark > last_mark:
                self._progress_marks[task_id] = mark
                self._queue_notification(updated, kind="progress")

    def _publish_progress(self, task: TaskRecord) -> None:
        if self._progress_publisher is None:
            return
        try:
            self._progress_publisher(
                {
                    "progress_id": task.id,
                    "title": task.title,
                    "percent": task.progress,
                    "text": task.result_summary or task.error or task.status,
                    "status": task.status,
                    "task_id": task.id,
                }
            )
        except Exception:
            logger.exception("task_progress_publish_failed task_id=%s", task.id)

    def _schedule_dependents(self, completed_id: str) -> None:
        completed = self.store.get(completed_id)
        for task in self.store.list(completed.user_id, limit=100):
            if completed_id in task.dependencies and task.status in {TaskStatus.PENDING, TaskStatus.WAITING}:
                if task.status == TaskStatus.WAITING:
                    self.store.update(task.id, status=TaskStatus.PENDING)
                self._schedule_if_ready(task.id)

    def _queue_notification(self, task: TaskRecord, *, kind: str = "completion") -> None:
        with self._lock:
            self._notifications.append(
                {
                    "task_id": task.id,
                    "kind": kind,
                    "user_id": task.user_id,
                    "title": task.title,
                    "worker_type": task.worker_type,
                    "status": task.status,
                    "progress": task.progress,
                    "result_summary": task.result_summary,
                    "error": task.error,
                }
            )

    def drain_notifications(self, user_id: str, limit: int = 3) -> list[dict[str, Any]]:
        """Return and remove completed task notifications for one user."""
        if limit < 1:
            raise ValueError("Notification limit must be positive.")
        with self._lock:
            matching = [
                item for item in self._notifications if item["user_id"] == user_id
            ]
            selected = matching[:limit]
            selected_ids = {id(item) for item in selected}
            self._notifications = [
                item for item in self._notifications if id(item) not in selected_ids
            ]
            return selected

    def get_status(self, task_id: str, user_id: str | None = None) -> dict[str, Any]:
        return self.store.get(task_id, user_id=user_id).as_dict()

    def list_tasks(self, user_id: str = "default", limit: int = 20) -> list[dict[str, Any]]:
        return [task.as_dict() for task in self.store.list(user_id, limit)]

    def list_active_tasks(self, user_id: str = "default", limit: int = 20) -> list[dict[str, Any]]:
        """List only tasks that still require execution or monitoring."""
        if limit < 1:
            raise ValueError("Task limit must be positive.")
        return [
            task.as_dict()
            for task in self.store.list(user_id, limit=limit * 2)
            if task.status in {
                TaskStatus.PENDING,
                TaskStatus.RUNNING,
                TaskStatus.WAITING,
            }
        ][:limit]

    def cancel(self, task_id: str, user_id: str | None = None) -> dict[str, Any]:
        task = self.store.get(task_id, user_id=user_id)
        if task.status in TERMINAL_STATUSES:
            return task.as_dict()
        future = self._futures.get(task_id)
        if future is not None:
            future.cancel()
        return self.store.update(task_id, status=TaskStatus.CANCELLED, error="Cancelled by user.").as_dict()

    def retry(self, task_id: str, user_id: str | None = None) -> dict[str, Any]:
        task = self.store.get(task_id, user_id=user_id)
        if task.status not in {TaskStatus.FAILED, TaskStatus.CANCELLED}:
            raise ValueError("Only failed or cancelled tasks can be retried.")
        self.store.update(task_id, status=TaskStatus.PENDING, progress=0, error="")
        self._schedule_if_ready(task_id)
        return self.store.get(task_id).as_dict()

    def shutdown(self, wait: bool = True) -> None:
        self._stop_scheduler.set()
        self._scheduler.join(timeout=2)
        self._executor.shutdown(wait=wait, cancel_futures=True)


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _parse_schedule_time(value: str, timezone_name: str) -> datetime:
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
        zone = ZoneInfo(timezone_name)
    except (ValueError, ZoneInfoNotFoundError) as exc:
        raise ValueError("Schedule run_at must be ISO-8601 and timezone must be valid.") from exc
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=zone)
    return parsed.astimezone(timezone.utc)


def _next_schedule_time(previous: str, recurrence: str, timezone_name: str) -> str:
    current_utc = _parse_schedule_time(previous, timezone_name)
    zone = ZoneInfo(timezone_name)
    local = current_utc.astimezone(zone)
    delta = timedelta(days=1 if recurrence == "daily" else 7)
    return (local + delta).astimezone(timezone.utc).isoformat()
