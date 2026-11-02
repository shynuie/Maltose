"""Durable local task orchestration primitives."""

from __future__ import annotations

import json
import hashlib
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
from contextlib import nullcontext
from maltose.runtime.control import AutonomyControl, AutonomyPaused

logger = logging.getLogger(__name__)


def _is_uuid(value: object) -> bool:
    if not isinstance(value, str):
        return False
    try:
        uuid.UUID(value)
    except ValueError:
        return False
    return True


class TaskStatus:
    PENDING = "pending"
    RUNNING = "running"
    WAITING = "waiting"
    HELD = "held"
    SUCCEEDED = "succeeded"
    FAILED = "failed"
    CANCELLED = "cancelled"


class ScheduleStatus:
    ACTIVE = "active"
    PAUSED = "paused"
    COMPLETED = "completed"
    HELD = "held"
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
    workflow: dict[str, Any] | None = None
    dispatch_ready: bool = True

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
            workflow=json.loads(row['workflow_json']) if row['workflow_json'] else None,
            dispatch_ready=bool(row['dispatch_ready']),
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
            "workflow": self.workflow,
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
        self.notification_session = uuid.uuid4().hex
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
            self._connection.execute('''CREATE TABLE IF NOT EXISTS task_notifications (
                id TEXT PRIMARY KEY, task_id TEXT NOT NULL REFERENCES tasks(id), user_id TEXT NOT NULL,
                payload_json TEXT NOT NULL, created_at TEXT NOT NULL, producer_session TEXT NOT NULL,
                delivery_status TEXT NOT NULL DEFAULT 'pending', result_json TEXT,
                speech_claimed INTEGER NOT NULL DEFAULT 0)''')
            if 'followup_checked' not in {row['name'] for row in self._connection.execute('PRAGMA table_info(task_notifications)')}:
                self._connection.execute('ALTER TABLE task_notifications ADD COLUMN followup_checked INTEGER NOT NULL DEFAULT 0')
            self._connection.execute('CREATE INDEX IF NOT EXISTS idx_task_notifications_pending ON task_notifications(user_id, delivery_status, created_at)')
            self._connection.execute('''CREATE TABLE IF NOT EXISTS task_attempts (
                id TEXT PRIMARY KEY, task_id TEXT NOT NULL REFERENCES tasks(id), user_id TEXT NOT NULL,
                phase TEXT NOT NULL, workflow_json TEXT, observations_json TEXT NOT NULL DEFAULT '[]',
                created_at TEXT NOT NULL)''')
            self._connection.execute('''CREATE TABLE IF NOT EXISTS product_continuations (
                id TEXT PRIMARY KEY, user_id TEXT NOT NULL, trigger_id TEXT NOT NULL REFERENCES task_notifications(id),
                payload_json TEXT NOT NULL, phase TEXT NOT NULL DEFAULT 'ready', session_id TEXT,
                result_json TEXT, observations_json TEXT NOT NULL DEFAULT '[]', speech_claimed INTEGER NOT NULL DEFAULT 0)''')
            self._connection.execute('CREATE INDEX IF NOT EXISTS idx_product_continuations_pending ON product_continuations(user_id,phase)')
            self._connection.execute('''CREATE TABLE IF NOT EXISTS foreground_results (
                id TEXT PRIMARY KEY, conversation_id TEXT NOT NULL, payload_json TEXT NOT NULL,
                phase TEXT NOT NULL DEFAULT 'pending', assessment_json TEXT, speech_claimed INTEGER NOT NULL DEFAULT 0)''')
            self._connection.execute('CREATE INDEX IF NOT EXISTS idx_foreground_results_pending ON foreground_results(conversation_id,phase)')
            self._connection.execute('''CREATE TABLE IF NOT EXISTS foreground_presentations (
                id TEXT PRIMARY KEY REFERENCES foreground_results(id), conversation_id TEXT NOT NULL,
                context_json TEXT NOT NULL, decision_json TEXT)''')
            if 'followup_checked' not in {row['name'] for row in self._connection.execute('PRAGMA table_info(foreground_results)')}:
                self._connection.execute('ALTER TABLE foreground_results ADD COLUMN followup_checked INTEGER NOT NULL DEFAULT 0')
            self._connection.execute('''CREATE TABLE IF NOT EXISTS foreground_continuations (
                id TEXT PRIMARY KEY, conversation_id TEXT NOT NULL,
                foreground_id TEXT NOT NULL REFERENCES foreground_results(id),
                parent_id TEXT REFERENCES foreground_continuations(id), payload_json TEXT NOT NULL,
                phase TEXT NOT NULL DEFAULT 'ready', session_id TEXT, result_json TEXT,
                observations_json TEXT NOT NULL DEFAULT '[]', speech_claimed INTEGER NOT NULL DEFAULT 0,
                followup_checked INTEGER NOT NULL DEFAULT 0)''')
            self._connection.execute('CREATE INDEX IF NOT EXISTS idx_foreground_continuations_pending ON foreground_continuations(conversation_id,phase)')
            if 'workflow_json' not in {row['name'] for row in self._connection.execute('PRAGMA table_info(tasks)')}:
                self._connection.execute('ALTER TABLE tasks ADD COLUMN workflow_json TEXT')
            if 'dispatch_ready' not in {row['name'] for row in self._connection.execute('PRAGMA table_info(tasks)')}:
                self._connection.execute('ALTER TABLE tasks ADD COLUMN dispatch_ready INTEGER NOT NULL DEFAULT 1')

    def close(self) -> None:
        with self._lock:
            self._connection.close()

    def begin_attempt(self, task_id, attempt_id):
        if not isinstance(attempt_id, str) or len(attempt_id) != 32 or any(c not in '0123456789abcdef' for c in attempt_id): raise ValueError('Invalid attempt ID')
        with self._lock, self._connection:
            task = self.get(task_id)
            if task.status != TaskStatus.PENDING: raise ValueError('Admit an attempt only for pending work')
            existing = self._connection.execute('SELECT task_id,phase FROM task_attempts WHERE id=?', (attempt_id,)).fetchone()
            if existing is not None and existing['task_id'] == task_id and existing['phase'] in {'prepared','admitted','uncertain'}:
                self._connection.execute("UPDATE task_attempts SET phase='prepared' WHERE id=?", (attempt_id,))
                self._connection.execute('UPDATE tasks SET status=?,progress=1,updated_at=? WHERE id=?', (TaskStatus.RUNNING, _now(), task_id))
                return self.get(task_id)
            if self._connection.execute("SELECT 1 FROM task_attempts WHERE task_id=? AND phase IN ('prepared','admitted','running','uncertain')", (task_id,)).fetchone():
                raise RuntimeError('A previous attempt still needs reconciliation')
            self._connection.execute('INSERT INTO task_attempts(id,task_id,user_id,phase,created_at) VALUES(?,?,?,?,?)',
                (attempt_id, task_id, task.user_id, 'prepared', _now()))
            self._connection.execute('UPDATE tasks SET status=?, progress=1, updated_at=? WHERE id=?', (TaskStatus.RUNNING, _now(), task_id))
        return self.get(task_id)

    def unstarted_attempt(self, task_id):
        with self._lock:
            row = self._connection.execute("SELECT id FROM task_attempts WHERE task_id=? AND phase IN ('prepared','admitted','uncertain') ORDER BY rowid LIMIT 1", (task_id,)).fetchone()
            return row['id'] if row else None

    def completed_attempt_reports(self, task_id, user_id):
        with self._lock:
            rows = self._connection.execute("SELECT payload_json,id FROM task_notifications WHERE task_id=? AND user_id=? AND json_extract(payload_json,'$.kind')='completion' ORDER BY created_at,rowid", (task_id, user_id)).fetchall()
        if len(rows) > 512: raise ValueError('Attempt history exceeds the product budget')
        reports = []
        for row in rows:
            item = json.loads(row['payload_json']); binding = item.get('attempt_workflow')
            if not binding: continue
            actual = self.attempt(binding['attemptID'], user_id)
            if actual['phase'] != 'finished' or actual['workflow'] != binding: raise ValueError('Stored attempt source changed')
            reports.append({**binding, 'workerID': task_id, 'workerState': item['status'], 'resultID': 'task-result:' + row['id'],
                'resultDigest': hashlib.sha256((item['result_summary'] or item['error'] or '').encode()).hexdigest(),
                'observations': actual['observations']})
        return reports

    def admit_attempt(self, attempt_id, workflow):
        with self._lock, self._connection:
            row = self._connection.execute('SELECT * FROM task_attempts WHERE id=?', (attempt_id,)).fetchone()
            if row is None or row['phase'] != 'prepared': raise ValueError('Attempt admission source changed')
            self._connection.execute("UPDATE task_attempts SET phase='admitted',workflow_json=? WHERE id=?", (json.dumps(workflow) if workflow else None, attempt_id))

    def attempt(self, attempt_id, user_id):
        with self._lock:
            row = self._connection.execute('SELECT * FROM task_attempts WHERE id=? AND user_id=?', (attempt_id, user_id)).fetchone()
            if row is None: raise KeyError('Unknown attempt owner')
            return dict(id=row['id'], task_id=row['task_id'], phase=row['phase'],
                workflow=json.loads(row['workflow_json']) if row['workflow_json'] else None, observations=json.loads(row['observations_json']))

    def mark_attempt_running(self, attempt_id):
        with self._lock, self._connection:
            if self._connection.execute("UPDATE task_attempts SET phase='running' WHERE id=? AND phase='admitted'", (attempt_id,)).rowcount != 1:
                raise ValueError('Attempt was not admitted')

    def finish_unused_attempt(self, attempt_id, *, held=False):
        with self._lock, self._connection:
            row = self._connection.execute("SELECT task_id FROM task_attempts WHERE id=? AND phase='admitted'", (attempt_id,)).fetchone()
            if row is None: return
            if held:
                self._connection.execute('UPDATE tasks SET status=?,error=?,updated_at=? WHERE id=? AND status=?',
                    (TaskStatus.HELD, 'Execution was not entered before the control handoff.', _now(), row['task_id'], TaskStatus.RUNNING))
            self._connection.execute("UPDATE task_attempts SET phase='finished' WHERE id=?", (attempt_id,))
            self._insert_notification(self.get(row['task_id']), 'completion', attempt_id=attempt_id)

    def hold_deferred_work(self) -> dict[str, int]:
        """Called only after the execution gate has drained, before a new intent."""
        with self._lock, self._connection:
            tasks = self._connection.execute(
                "UPDATE tasks SET status = ?, updated_at = ? WHERE status IN (?, ?, ?)",
                (TaskStatus.HELD, _now(), TaskStatus.PENDING, TaskStatus.WAITING, TaskStatus.RUNNING)).rowcount
            schedules = self._connection.execute(
                "UPDATE schedules SET status = ?, updated_at = ? WHERE status = ?",
                (ScheduleStatus.HELD, _now(), ScheduleStatus.ACTIVE)).rowcount
        return {'tasks': tasks, 'schedules': schedules}

    def create(
        self,
        title: str,
        worker_type: str,
        input: dict[str, Any] | None = None,
        dependencies: list[str] | None = None,
        user_id: str = "default",
        task_id: str | None = None,
        dispatch_ready: bool = True,
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
                    progress, dependencies_json, created_at, updated_at, dispatch_ready
                ) VALUES (?, ?, ?, ?, ?, ?, 0, ?, ?, ?, ?)
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
                    int(dispatch_ready),
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
        notification_kind: str | None = None,
        attempt_id: str | None = None,
        observations: list | None = None,
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
            if attempt_id is not None:
                row = self._connection.execute('SELECT task_id,phase FROM task_attempts WHERE id=?', (attempt_id,)).fetchone()
                if row is None or row['task_id'] != task_id or row['phase'] not in {'prepared','admitted','running'}: raise ValueError('Attempt result source changed')
                encoded = json.dumps(observations or [], ensure_ascii=False, allow_nan=False)
                if len(encoded.encode()) > 2 * 1024 * 1024 or len(observations or []) > 64: raise ValueError('Attempt evidence exceeds budget')
                phase = 'finished' if status in TERMINAL_STATUSES else 'uncertain'
                self._connection.execute('UPDATE task_attempts SET phase=?,observations_json=? WHERE id=?', (phase, encoded, attempt_id))
            cursor = self._connection.execute(
                f"UPDATE tasks SET {', '.join(updates)} WHERE id = ?", values
            )
            if cursor.rowcount == 0:
                raise KeyError(f"Unknown task: {task_id}")
            record = self.get(task_id)
            if notification_kind is not None: self._insert_notification(record, notification_kind, attempt_id=attempt_id)
            return record

    def _insert_notification(self, task: TaskRecord, kind: str, *, attempt_id=None) -> str:
        if kind not in {'progress', 'completion'}: raise ValueError('Invalid task notification kind')
        identity = str(uuid.uuid5(uuid.NAMESPACE_URL, f'maltose:task-notification:{task.id}:{kind}:{task.updated_at}:{task.status}:{task.progress}'))
        payload = dict(schemaVersion=1, task_id=task.id, kind=kind, user_id=task.user_id, title=task.title,
            worker_type=task.worker_type, status=task.status, progress=task.progress,
            result_summary=task.result_summary, error=task.error, workflow=task.workflow)
        if attempt_id is not None:
            attempt = self.attempt(attempt_id, task.user_id)
            payload['attempt_workflow'] = attempt['workflow']
        if kind == 'completion':
            self._connection.execute("UPDATE task_notifications SET delivery_status='superseded' WHERE task_id=? AND delivery_status='pending' AND json_extract(payload_json,'$.kind')='progress'", (task.id,))
        self._connection.execute('''INSERT OR IGNORE INTO task_notifications
            (id,task_id,user_id,payload_json,created_at,producer_session) VALUES (?,?,?,?,?,?)''',
            (identity, task.id, task.user_id, json.dumps(payload, ensure_ascii=True, allow_nan=False), task.updated_at, self.notification_session))
        return identity

    def enqueue_notification(self, task: TaskRecord, *, kind='completion') -> str:
        with self._lock, self._connection: return self._insert_notification(task, kind)

    def pending_notifications(self, user_id: str, limit: int = 3) -> list[dict]:
        if type(limit) is not int or not 1 <= limit <= 100: raise ValueError('Invalid notification limit')
        with self._lock:
            rows = self._connection.execute("SELECT * FROM task_notifications WHERE user_id=? AND delivery_status='pending' ORDER BY created_at,rowid LIMIT ?", (user_id, limit)).fetchall()
        return [{**json.loads(row['payload_json']), 'notification_id': row['id'],
            'recovered': row['producer_session'] != self.notification_session,
            'speech_claimed': bool(row['speech_claimed']),
            'prepared_result': json.loads(row['result_json']) if row['result_json'] else None} for row in rows]

    def scoped_product_notifications(self, grants, *, pending_only=False):
        if not isinstance(grants,list) or len(grants)>128:raise ValueError('Invalid worker delivery scopes')
        rows=[];seen=set()
        with self._lock:
            for grant in grants:
                if not isinstance(grant,dict) or any(key not in grant for key in ('workerID','attemptID','taskID','inputID','requirementsRevision','planVersion')):raise ValueError('Incomplete worker scope')
                if not _is_uuid(grant['taskID']) or any(not isinstance(grant[key],str) or not grant[key] or len(grant[key].encode())>128 for key in ('workerID','inputID')) or any(type(grant[key]) is not int or grant[key]<1 for key in ('requirementsRevision','planVersion')):raise ValueError('Invalid worker scope')
                candidates=self._connection.execute("SELECT * FROM task_notifications WHERE task_id=? AND delivery_status IN ('pending','accepted') AND json_extract(payload_json,'$.kind')='completion' ORDER BY rowid",(grant['workerID'],)).fetchall()
                for row in candidates:
                    value=json.loads(row['payload_json']);source=value.get('attempt_workflow') or {}
                    if any(source.get(key)!=grant[key] for key in ('taskID','inputID','requirementsRevision','planVersion','attemptID')):continue
                    attempt=self.attempt(grant['attemptID'],row['user_id'])
                    if row['user_id']!=value['user_id'] or attempt['task_id']!=grant['workerID'] or attempt['workflow']!=source or attempt['phase']!='finished':raise ValueError('Worker result owner or attempt mismatch')
                    if row['id'] in seen or pending_only and row['delivery_status']!='pending':continue
                    seen.add(row['id']);rows.append({**value,'notification_id':row['id'],'delivery_status':row['delivery_status'],'followup_checked':bool(row['followup_checked']),
                        'native_managed':('task-result:'+row['id']) in grant.get('managedResults',[]),
                        'recovered':row['producer_session']!=self.notification_session,'speech_claimed':bool(row['speech_claimed']),
                        'prepared_result':json.loads(row['result_json']) if row['result_json'] else None})
        return rows

    def mark_worker_followup(self, identity, owner):
        with self._lock,self._connection:
            cursor=self._connection.execute("UPDATE task_notifications SET followup_checked=1 WHERE id=? AND user_id=? AND delivery_status='accepted'",(identity,owner))
            if cursor.rowcount!=1:raise KeyError('Worker followup source is not acknowledged')

    def pending_notification_ids(self, user_id: str, limit: int = 100) -> list[str]:
        with self._lock:
            return [row['id'] for row in self._connection.execute("SELECT id FROM task_notifications WHERE user_id=? AND delivery_status='pending' ORDER BY created_at,rowid LIMIT ?", (user_id, limit)).fetchall()]

    def delivered_product_results(self, user_id, reference):
        """Already acknowledged full publications, for this owner/version only."""
        with self._lock:
            rows = self._connection.execute("SELECT result_json FROM task_notifications WHERE user_id=? AND delivery_status='accepted' AND result_json IS NOT NULL AND json_extract(payload_json,'$.kind')='completion' ORDER BY created_at,rowid", (user_id,)).fetchall()
        results = []; size = 0
        for row in rows:
            value = json.loads(row['result_json']); source = value.get('workflow_ref') or {}
            if not source.get('attemptID') or any(source.get(key) != reference.get(key) for key in ('taskID', 'requirementsRevision', 'planVersion')): continue
            item = dict(resultID=value['result_id'], executionID=source['executionID'], full_text=value['full_text'],
                limitations=value['limitations'], chatStored=True)
            size += len(json.dumps(item, ensure_ascii=False).encode())
            if len(results) >= 64 or size > 192 * 1024: return {'complete': False, 'results': []}
            results.append(item)
        return {'complete': True, 'results': results}

    def prepare_foreground_result(self, conversation_id, payload):
        raw = json.dumps(payload, ensure_ascii=False, allow_nan=False, sort_keys=True)
        if len(raw.encode()) > 2 * 1024 * 1024: raise ValueError('Foreground result and receipts exceed budget')
        identity = payload['result']['result_id']
        with self._lock, self._connection:
            previous = self._connection.execute('SELECT * FROM foreground_results WHERE id=?', (identity,)).fetchone()
            if previous is not None:
                if previous['conversation_id'] != conversation_id or previous['payload_json'] != raw:
                    raise ValueError('Foreground result source/content are immutable')
            else:
                self._connection.execute('INSERT INTO foreground_results(id,conversation_id,payload_json) VALUES(?,?,?)', (identity, conversation_id, raw))
        return self.foreground_result(identity, conversation_id)

    def foreground_result(self, identity, conversation_id):
        with self._lock:
            row = self._connection.execute('SELECT * FROM foreground_results WHERE id=? AND conversation_id=?', (identity, conversation_id)).fetchone()
            if row is None: raise KeyError('Unknown foreground conversation/source')
            return {**dict(row), 'payload': json.loads(row['payload_json']),
                'assessment': json.loads(row['assessment_json']) if row['assessment_json'] else None}

    def foreground_presentation(self, identity, conversation_id):
        with self._lock:
            self.foreground_result(identity,conversation_id)
            row=self._connection.execute('SELECT * FROM foreground_presentations WHERE id=? AND conversation_id=?',(identity,conversation_id)).fetchone()
            return None if row is None else dict(context=json.loads(row['context_json']),decision=json.loads(row['decision_json']) if row['decision_json'] is not None else None)

    def prepare_foreground_presentation(self, identity, conversation_id, context):
        raw=json.dumps(context,ensure_ascii=False,allow_nan=False,sort_keys=True)
        if len(raw.encode())>192*1024:raise ValueError('Presentation source context exceeds budget')
        with self._lock,self._connection:
            row=self.foreground_result(identity,conversation_id)
            if row['phase']!='pending' or row['assessment'] is not None or row['payload']['result']['chart'] is not None:
                raise ValueError('Presentation must precede first publication and cannot replace a chart')
            previous=self._connection.execute('SELECT * FROM foreground_presentations WHERE id=?',(identity,)).fetchone()
            if previous:
                if previous['conversation_id']!=conversation_id or previous['context_json']!=raw:raise ValueError('Presentation source is immutable')
            else:self._connection.execute('INSERT INTO foreground_presentations(id,conversation_id,context_json) VALUES(?,?,?)',(identity,conversation_id,raw))

    def save_foreground_presentation(self, identity, conversation_id, decision):
        from maltose.visual_planning import construct_chart
        if not isinstance(decision,dict) or set(decision)!={'chart','decision'}:raise ValueError('Invalid saved presentation')
        with self._lock,self._connection:
            source=self.foreground_result(identity,conversation_id);plan=self.foreground_presentation(identity,conversation_id)
            if source['phase']!='pending' or plan is None:raise ValueError('Missing pending presentation source')
            chart=construct_chart(decision['decision'],plan['context'])
            if (chart.to_dict() if chart else None)!=decision['chart']:raise ValueError('Presentation changed source values')
            raw=json.dumps(decision,ensure_ascii=False,allow_nan=False,sort_keys=True)
            if len(raw.encode())>160*1024:raise ValueError('Presentation decision exceeds budget')
            if plan['decision'] is not None and plan['decision']!=decision:raise ValueError('Saved presentation is immutable')
            self._connection.execute('UPDATE foreground_presentations SET decision_json=? WHERE id=?',(raw,identity))

    def prepared_foreground_answer(self, identity, conversation_id):
        from dataclasses import replace
        from maltose.presentation import AnswerResult,ResultChart
        with self._lock:
            row=self.foreground_result(identity,conversation_id)
            result=AnswerResult.from_record(row['payload']['result']);plan=self.foreground_presentation(identity,conversation_id)
            return replace(result,chart=ResultChart.from_dict(plan['decision']['chart'])) if plan and plan['decision'] and plan['decision']['chart'] else result

    def pending_foreground_results(self, conversation_id):
        with self._lock:
            return [self.foreground_result(row['id'], conversation_id) for row in self._connection.execute(
                "SELECT id FROM foreground_results WHERE conversation_id=? AND phase='pending' ORDER BY rowid LIMIT 16", (conversation_id,)).fetchall()]

    def save_foreground_assessment(self, identity, conversation_id, assessment):
        raw = json.dumps(assessment, ensure_ascii=False, allow_nan=False, sort_keys=True)
        if len(raw.encode()) > 128 * 1024: raise ValueError('Foreground review exceeds budget')
        with self._lock, self._connection:
            row = self.foreground_result(identity, conversation_id)
            if row['assessment_json'] is not None and row['assessment_json'] != raw: raise ValueError('Foreground assessment is immutable')
            self._connection.execute('UPDATE foreground_results SET assessment_json=? WHERE id=?', (raw, identity))

    def finish_foreground_result(self, identity, conversation_id, *, superseded=False):
        with self._lock, self._connection:
            row = self.foreground_result(identity, conversation_id)
            if row['phase'] == 'pending': self._connection.execute('UPDATE foreground_results SET phase=? WHERE id=?', ('superseded' if superseded else 'delivered', identity))

    def claim_foreground_speech(self, identity, conversation_id):
        with self._lock, self._connection:
            return self._connection.execute("UPDATE foreground_results SET speech_claimed=1 WHERE id=? AND conversation_id=? AND phase='delivered' AND speech_claimed=0", (identity, conversation_id)).rowcount == 1

    def pending_foreground_followups(self, conversation_id):
        with self._lock:
            return [self.foreground_result(row['id'], conversation_id) for row in self._connection.execute(
                "SELECT id FROM foreground_results WHERE conversation_id=? AND phase='delivered' AND followup_checked=0 ORDER BY rowid LIMIT 16", (conversation_id,)).fetchall()]

    def mark_foreground_followup(self, identity, conversation_id, *, continuation=False):
        table = 'foreground_continuations' if continuation else 'foreground_results'
        with self._lock, self._connection:
            if self._connection.execute(f"UPDATE {table} SET followup_checked=1 WHERE id=? AND conversation_id=? AND phase='delivered'", (identity,conversation_id)).rowcount != 1:
                raise KeyError('Foreground followup requires acknowledged delivery')

    def enqueue_foreground_continuation(self, conversation_id, foreground_id, payload, *, parent_id=None):
        raw = json.dumps(payload, ensure_ascii=False, allow_nan=False, sort_keys=True)
        if len(raw.encode()) > 512 * 1024: raise ValueError('Foreground continuation context exceeds budget')
        with self._lock, self._connection:
            root = self.foreground_result(foreground_id, conversation_id)
            reference = root['payload']['reference']
            if root['phase'] != 'delivered' or not reference or payload.get('foregroundID') != foreground_id or any(payload.get(key) != reference.get(key) for key in ('taskID','inputID','requirementsRevision','planVersion')):
                raise ValueError('Foreground continuation requires its real delivered source')
            if payload.get('resumeAfterID'):
                answer = self.foreground_result(payload['resumeAfterID'],conversation_id)
                if answer['phase'] != 'delivered' or answer['payload']['reference'] is not None or answer['payload']['result']['kind'] != 'answer' or answer['payload']['inputID'] == reference['inputID']:
                    raise ValueError('Resumption requires a separate delivered foreground answer')
            if parent_id:
                parent = self.foreground_continuation(parent_id, conversation_id)
                if parent['phase'] != 'delivered' or parent['foreground_id'] != foreground_id: raise ValueError('Continuation parent is not delivered in this scope')
                source = parent_id
            else: source = foreground_id
            if payload.get('sourceOutcomeID') not in (source,'assessment:'+source) or payload.get('mode') not in ('work','clarify'):
                raise ValueError('Foreground continuation source/mode mismatch')
            previous = self._connection.execute('SELECT * FROM foreground_continuations WHERE id=?',(payload['id'],)).fetchone()
            if previous:
                if previous['conversation_id'] != conversation_id or previous['foreground_id'] != foreground_id or previous['parent_id'] != parent_id or previous['payload_json'] != raw:
                    raise ValueError('Foreground continuation source and context are immutable')
            else:
                self._connection.execute('INSERT INTO foreground_continuations(id,conversation_id,foreground_id,parent_id,payload_json) VALUES(?,?,?,?,?)',
                    (payload['id'],conversation_id,foreground_id,parent_id,raw))

    def foreground_continuation(self, identity, conversation_id):
        with self._lock:
            row=self._connection.execute('SELECT * FROM foreground_continuations WHERE id=? AND conversation_id=?',(identity,conversation_id)).fetchone()
            if row is None: raise KeyError('Unknown foreground continuation conversation')
            value=dict(row)
            value.update(payload=json.loads(row['payload_json']),observations=json.loads(row['observations_json']),
                         result=json.loads(row['result_json']) if row['result_json'] else None)
            return value

    def pending_foreground_continuations(self, conversation_id, session_id):
        with self._lock, self._connection:
            rows=self._connection.execute('''SELECT c.*,r.payload_json AS root_payload FROM foreground_continuations c
                JOIN foreground_results r ON r.id=c.foreground_id
                LEFT JOIN foreground_continuations p ON p.id=c.parent_id
                WHERE c.conversation_id=? AND r.conversation_id=? AND r.phase='delivered'
                AND (c.parent_id IS NULL OR p.phase='delivered')
                AND (c.phase IN ('ready','admitting','running','generated') OR (c.phase='delivered' AND c.followup_checked=0))
                ORDER BY c.rowid LIMIT 16''',(conversation_id,conversation_id)).fetchall()
            pending=[]
            for row in rows:
                value=self.foreground_continuation(row['id'],conversation_id)
                if value['phase']=='running' and value['session_id'] != session_id:
                    # Work may have changed real state. Keep it uncertain; never rerun it.
                    self._connection.execute("UPDATE foreground_continuations SET phase='uncertain' WHERE id=?",(row['id'],))
                    continue
                if value['phase']=='running': continue
                value['recovered']=value['session_id'] not in (None,session_id) or json.loads(row['root_payload'])['producerSessionID'] != session_id
                pending.append(value)
            return pending

    def update_foreground_continuation(self, identity, conversation_id, phase, *, session_id=None, result=None, observations=None):
        if phase not in ('admitting','running','generated','delivered','interrupted'): raise ValueError('Invalid foreground continuation phase')
        with self._lock,self._connection:
            row=self.foreground_continuation(identity,conversation_id)
            if row['phase'] in ('delivered','interrupted','uncertain'): raise RuntimeError('Foreground continuation is terminal or uncertain')
            body=json.dumps(result,ensure_ascii=False,allow_nan=False) if result is not None else row['result_json']
            receipts=json.dumps(observations,ensure_ascii=False,allow_nan=False) if observations is not None else row['observations_json']
            if row['result_json'] is not None and (row['result_json'] != body or row['observations_json'] != receipts): raise ValueError('Saved foreground continuation output is immutable')
            if len((body or '').encode())+len(receipts.encode()) > 2*1024*1024: raise ValueError('Foreground continuation output exceeds budget')
            self._connection.execute('UPDATE foreground_continuations SET phase=?,session_id=?,result_json=?,observations_json=? WHERE id=?',
                (phase,session_id or row['session_id'],body,receipts,identity))

    def claim_foreground_continuation_speech(self, identity, conversation_id):
        with self._lock,self._connection:
            return self._connection.execute("UPDATE foreground_continuations SET speech_claimed=1 WHERE id=? AND conversation_id=? AND phase='delivered' AND speech_claimed=0",(identity,conversation_id)).rowcount==1

    def delivered_foreground_results(self, conversation_id, foreground_id):
        from maltose.presentation import AnswerResult
        with self._lock:
            root=self.foreground_result(foreground_id,conversation_id)
            if root['phase'] != 'delivered': return dict(results=[],complete=False)
            records=[self.prepared_foreground_answer(foreground_id,conversation_id).to_record()]
            for row in self._connection.execute("SELECT result_json FROM foreground_continuations WHERE conversation_id=? AND foreground_id=? AND phase='delivered' ORDER BY rowid",(conversation_id,foreground_id)):
                if row['result_json']: records.append(json.loads(row['result_json']))
            if len(json.dumps(records,ensure_ascii=False).encode()) > 192*1024: return dict(results=[],complete=False)
            values=[AnswerResult.from_record(record) for record in records]
            return dict(results=[dict(resultID=v.result_id,full_text=v.display_text,limitations=list(v.limitations),chatStored=True) for v in values],complete=True)

    def enqueue_continuation(self, user_id, trigger_id, payload):
        raw = json.dumps(payload, ensure_ascii=False, allow_nan=False)
        if len(raw.encode()) > 512 * 1024: raise ValueError('Complete continuation context exceeds budget')
        with self._lock, self._connection:
            if not self._connection.execute('SELECT 1 FROM task_notifications WHERE id=? AND user_id=?', (trigger_id, user_id)).fetchone(): raise KeyError('Unknown continuation owner')
            self._connection.execute('INSERT OR IGNORE INTO product_continuations(id,user_id,trigger_id,payload_json) VALUES(?,?,?,?)',
                (payload['id'], user_id, trigger_id, raw))

    def pending_continuations(self, user_id, session_id, *, trigger_ids=None):
        with self._lock, self._connection:
            rows = self._connection.execute('''SELECT c.* FROM product_continuations c JOIN task_notifications n ON c.trigger_id=n.id
                WHERE c.user_id=? AND c.phase IN ('ready','admitting','running','generated') AND n.delivery_status='accepted'
                AND (? IS NULL OR c.trigger_id IN (SELECT value FROM json_each(?))) ORDER BY c.rowid''',
                (user_id,None if trigger_ids is None else 1,json.dumps(trigger_ids or []))).fetchall()
            pending = []
            for row in rows:
                value = dict(row); payload = json.loads(row['payload_json']); phase = row['phase']
                if phase == 'running' and row['session_id'] != session_id:
                    phase = 'uncertain' if payload['mode'] == 'work' else 'admitting'
                    self._connection.execute('UPDATE product_continuations SET phase=? WHERE id=?', (phase, row['id']))
                if phase not in {'ready', 'admitting', 'generated'}: continue
                value.update(payload=payload, phase=phase, result=json.loads(row['result_json']) if row['result_json'] else None,
                    observations=json.loads(row['observations_json']), recovered=row['session_id'] not in (None, session_id))
                pending.append(value)
            return pending

    def continuation(self, identity, user_id):
        with self._lock:
            row = self._connection.execute('SELECT * FROM product_continuations WHERE id=? AND user_id=?', (identity, user_id)).fetchone()
            if row is None: raise KeyError('Unknown continuation owner')
            return {**dict(row), 'payload': json.loads(row['payload_json']), 'observations': json.loads(row['observations_json'])}

    def update_continuation(self, identity, user_id, phase, *, session_id=None, result=None, observations=None):
        if phase not in {'admitting', 'running', 'generated', 'delivered', 'interrupted'}: raise ValueError('Invalid continuation phase')
        with self._lock, self._connection:
            row = self.continuation(identity, user_id)
            if row['phase'] in {'delivered', 'interrupted', 'uncertain'}: raise RuntimeError('Continuation is already terminal or uncertain')
            encoded = json.dumps(result, ensure_ascii=False, allow_nan=False) if result is not None else row['result_json']
            receipts = json.dumps(observations, ensure_ascii=False, allow_nan=False) if observations is not None else row['observations_json']
            if row['result_json'] is not None and (encoded != row['result_json'] or receipts != row['observations_json']):
                raise ValueError('Saved continuation content and evidence are immutable')
            if len((encoded or '').encode()) + len(receipts.encode()) > 2 * 1024 * 1024: raise ValueError('Continuation output exceeds budget')
            self._connection.execute('UPDATE product_continuations SET phase=?,session_id=?,result_json=?,observations_json=? WHERE id=?',
                (phase, session_id or row['session_id'], encoded, receipts, identity))

    def claim_continuation_speech(self, identity, user_id):
        with self._lock, self._connection:
            return self._connection.execute("UPDATE product_continuations SET speech_claimed=1 WHERE id=? AND user_id=? AND phase='delivered' AND speech_claimed=0", (identity, user_id)).rowcount == 1

    def prepare_notification_result(self, notification_id: str, user_id: str, result: dict) -> dict:
        encoded = json.dumps(result, ensure_ascii=True, allow_nan=False)
        if len(encoded.encode()) > 2 * 1024 * 1024: raise ValueError('Notification result is too large')
        with self._lock, self._connection:
            row = self._connection.execute('SELECT result_json FROM task_notifications WHERE id=? AND user_id=?', (notification_id, user_id)).fetchone()
            if row is None: raise KeyError('Unknown notification owner or identity')
            if row['result_json'] is not None: return json.loads(row['result_json'])
            self._connection.execute('UPDATE task_notifications SET result_json=? WHERE id=?', (encoded, notification_id))
            return result

    def bind_workflow(self, records: list[TaskRecord], bindings: dict) -> list[TaskRecord]:
        if not isinstance(bindings, dict) or set(bindings) != {record.id for record in records}: raise ValueError('Incomplete product task bindings')
        fields = {'schemaVersion', 'taskID', 'inputID', 'executionID', 'requirementsRevision', 'planVersion'}
        for record in records:
            value = bindings[record.id]
            if (not isinstance(value, dict) or set(value) != fields or type(value['schemaVersion']) is not int or value['schemaVersion'] != 1
                    or not _is_uuid(value['taskID']) or value['executionID'] != 'python:' + record.id
                    or not isinstance(value['inputID'], str) or not 1 <= len(value['inputID'].encode()) <= 128
                    or any(type(value[key]) is not int or value[key] < 1 for key in ('requirementsRevision', 'planVersion'))):
                raise ValueError('Invalid product task binding')
        with self._lock, self._connection:
            for record in records:
                current = self.get(record.id, user_id=record.user_id)
                if current.workflow is not None:
                    if current.workflow != bindings[record.id]: raise ValueError('Product execution binding is immutable')
                    continue
                if current.status != TaskStatus.PENDING: raise ValueError('Bind product work before dispatch')
                cursor = self._connection.execute('UPDATE tasks SET workflow_json=?, dispatch_ready=1 WHERE id=? AND user_id=?',
                    (json.dumps(bindings[record.id], allow_nan=False), record.id, record.user_id))
                if cursor.rowcount != 1: raise KeyError('Unknown product execution owner')
        return [self.get(record.id, user_id=record.user_id) for record in records]

    def acknowledge_notification(self, notification_id: str, user_id: str) -> None:
        with self._lock, self._connection:
            cursor = self._connection.execute("UPDATE task_notifications SET delivery_status='accepted' WHERE id=? AND user_id=? AND delivery_status IN ('pending','accepted')", (notification_id, user_id))
            if cursor.rowcount == 0: raise KeyError('Unknown or superseded notification')

    def claim_notification_speech(self, notification_id: str, user_id: str) -> bool:
        with self._lock, self._connection:
            cursor = self._connection.execute("UPDATE task_notifications SET speech_claimed=1 WHERE id=? AND user_id=? AND delivery_status='accepted' AND speech_claimed=0", (notification_id, user_id))
            return cursor.rowcount == 1

    def drain_notifications(self, user_id: str, limit: int = 3) -> list[dict]:
        # Compatibility for CLI/Web: native uses pending + explicit durable ACK.
        with self._lock, self._connection:
            selected = self.pending_notifications(user_id, limit)
            for item in selected:
                self._connection.execute("UPDATE task_notifications SET delivery_status='accepted' WHERE id=?", (item['notification_id'],))
            return selected

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


class TaskPlanNotDispatched(RuntimeError):
    def __init__(self, records):
        super().__init__('Product plan acknowledgement is unavailable; prepared work is held, not dispatched. Inspect before retrying.')
        self.records = records


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
        control_gate: AutonomyControl | None = None,
    ) -> None:
        if max_workers < 1:
            raise ValueError("max_workers must be positive.")
        if max_tasks_per_plan < 1:
            raise ValueError("max_tasks_per_plan must be positive.")
        self.store = store
        self.max_tasks_per_plan = max_tasks_per_plan
        self._workers = workers or {}
        self.attempt_observer = None
        self._progress_publisher = progress_publisher
        self.control_gate = control_gate
        if control_gate and not control_gate.active: self.store.hold_deferred_work()
        self._task_epochs: dict[str, int] = {}
        self._attempts: dict[str, str] = {}
        self._executor = ThreadPoolExecutor(
            max_workers=max_workers, thread_name_prefix="myagent-task"
        )
        self._futures: dict[str, Future[None]] = {}
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
        with self.control_gate.activity('schedule_create') if self.control_gate else nullcontext():
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
        if self.control_gate: self.control_gate.checkpoint()
        schedule = self.store.get_schedule(schedule_id, user_id=user_id)
        if schedule.status in {ScheduleStatus.PAUSED, ScheduleStatus.HELD}:
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
        try:
            with self.control_gate.activity('schedule_dispatch') if self.control_gate else nullcontext():
                self._dispatch_schedule(schedule)
        except AutonomyPaused:
            self.store.update_schedule(schedule.id, status=ScheduleStatus.HELD)

    def _dispatch_schedule(self, schedule: ScheduleRecord) -> None:
        # A row fetched before the gate closed may have been held while draining.
        if self.store.get_schedule(schedule.id).status != ScheduleStatus.ACTIVE: return
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
        except AutonomyPaused: raise
        except Exception as exc:
            self.store.update_schedule(schedule.id, error=str(exc), last_run_at=now)
            logger.exception("schedule_run_failed schedule_id=%s", schedule.id)

    @property
    def worker_types(self) -> tuple[str, ...]:
        return tuple(self._workers)

    def create_plan(
        self, tasks: list[dict[str, Any]], *, user_id: str = "default", plan_observer=None
    ) -> list[TaskRecord]:
        with self.control_gate.activity('plan_dispatch') if self.control_gate else nullcontext():
            return self._create_plan(tasks, user_id=user_id, plan_observer=plan_observer)

    def _create_plan(self, tasks: list[dict[str, Any]], *, user_id: str, plan_observer=None) -> list[TaskRecord]:
        if not tasks:
            raise ValueError("Task plan cannot be empty.")
        if len(tasks) > self.max_tasks_per_plan:
            raise ValueError(
                f"Task plan cannot contain more than {self.max_tasks_per_plan} tasks."
            )
        # ``task_id`` is a database identifier, not a human-readable task name.
        # Keep accepting it as a legacy dependency reference, but always create
        # a fresh UUID for the persisted record. ``task_ref`` is the preferred
        # short-lived alias for dependencies within this plan.
        refs: dict[str, str] = {}
        planned: list[tuple[dict[str, Any], str]] = []
        for item in tasks:
            requested_id = item.get("task_id")
            task_ref = item.get("task_ref") or (
                requested_id if requested_id and not _is_uuid(requested_id) else None
            )
            if task_ref:
                task_ref = str(task_ref)
                if task_ref in refs:
                    raise ValueError(f"Duplicate task_ref in plan: {task_ref}")
            task_id = str(uuid.uuid4())
            if task_ref:
                refs[task_ref] = task_id
            planned.append((item, task_id))
        records = []
        for item, task_id in planned:
            dependencies = item.get("dependencies", [])
            if not isinstance(dependencies, list):
                raise ValueError("Task dependencies must be a list.")
            dependencies = [refs.get(str(dep), str(dep)) for dep in dependencies]
            records.append(
                self.store.create(
                    title=str(item.get("title", "")),
                    worker_type=str(item.get("worker_type", "local")),
                    input=item.get("input", {}),
                    dependencies=dependencies,
                    user_id=user_id,
                    task_id=task_id,
                    dispatch_ready=plan_observer is None,
                )
            )
            if self.control_gate: self._task_epochs[task_id] = self.control_gate.epoch
        if plan_observer is not None:
            try:
                bindings = plan_observer(records)
                records = self.store.bind_workflow(records, bindings)
            except Exception as error:
                held = [self.store.update(record.id, status=TaskStatus.HELD) for record in records]
                raise TaskPlanNotDispatched(held) from error
        for record in records:
            self._schedule_if_ready(record.id)
        return records

    def _schedule_if_ready(self, task_id: str) -> None:
        try:
            epoch = self._task_epochs.get(task_id, self.control_gate.epoch if self.control_gate else None)
            with self.control_gate.activity('task_dispatch', expected_epoch=epoch) if self.control_gate else nullcontext():
                self._dispatch_if_ready(task_id, epoch)
        except AutonomyPaused:
            task = self.store.get(task_id)
            if task.status in {TaskStatus.PENDING, TaskStatus.WAITING}:
                self.store.update(task_id, status=TaskStatus.HELD)

    def _dispatch_if_ready(self, task_id: str, epoch: int | None) -> None:
        with self._lock:
            task = self.store.get(task_id)
            if task.status != TaskStatus.PENDING or not task.dispatch_ready:
                return
            dependencies = self.store.dependencies(task_id)
            if any(dep.status in {TaskStatus.PENDING, TaskStatus.RUNNING, TaskStatus.WAITING, TaskStatus.HELD} for dep in dependencies):
                self.store.update(task_id, status=TaskStatus.WAITING)
                return
            if any(dep.status in {TaskStatus.FAILED, TaskStatus.CANCELLED} for dep in dependencies):
                failed = self.store.update(
                    task_id,
                    status=TaskStatus.FAILED,
                    error="A dependency failed or was cancelled.",
                    notification_kind='completion',
                )
                self._queue_notification(failed)
                return
            worker = self._workers.get(task.worker_type)
            if worker is None:
                failed = self.store.update(
                    task_id,
                    status=TaskStatus.FAILED,
                    error=f"No worker registered for type: {task.worker_type}",
                    notification_kind='completion',
                )
                self._queue_notification(failed)
                return
            attempt = self.store.unstarted_attempt(task_id) or uuid.uuid4().hex
            running = self.store.begin_attempt(task_id, attempt)
            try:
                binding = self.attempt_observer(running, attempt) if self.attempt_observer and running.workflow else None
                self.store.admit_attempt(attempt, binding)
            except Exception:
                self.store.update(task_id, status=TaskStatus.HELD, error='Attempt acknowledgement is unknown; work was not dispatched. Inspect before retrying.', attempt_id=attempt)
                raise
            self._publish_progress(running)
            self._progress_marks[task_id] = 0
            self._attempts[task_id] = attempt
            self._futures[task_id] = self._executor.submit(self._run, task_id, worker, epoch, attempt)

    def _run(self, task_id: str, worker: TaskWorker, epoch: int | None, attempt: str) -> None:
        try:
            with self.control_gate.activity('background_task', expected_epoch=epoch) if self.control_gate else nullcontext():
                with self._lock:
                    if self._attempts.get(task_id) != attempt or self.store.get(task_id).status != TaskStatus.RUNNING: return
                    self.store.mark_attempt_running(attempt)
                self._run_admitted(task_id, worker, attempt=attempt)
        except AutonomyPaused:
            with self._lock:
                if self._attempts.get(task_id) == attempt and self.store.get(task_id).status == TaskStatus.RUNNING:
                    self.store.finish_unused_attempt(attempt, held=True)
        finally:
            with self._lock:
                if self._attempts.get(task_id) == attempt:
                    # No worker entered in this branch (cancelled queued Future
                    # or gate rejection). Its admission must not block retry.
                    phase = self.store.attempt(attempt, self.store.get(task_id).user_id)['phase']
                    if phase == 'admitted': self.store.finish_unused_attempt(attempt)
                    self._futures.pop(task_id, None)
                    self._progress_marks.pop(task_id, None)
                    self._attempts.pop(task_id, None)

    def _run_admitted(self, task_id: str, worker: TaskWorker, *, attempt=None) -> None:
        from maltose.tool_observations import collect_tool_returns
        observations = []
        try:
            task = self.store.get(task_id)
            with collect_tool_returns() as observations:
                result = worker.run(task, lambda progress: self._report_progress(task_id, progress))
        except Exception as exc:
            logger.exception("task_failed task_id=%s", task_id)
            with self._lock:
                current = self.store.get(task_id)
                cancelled = current.status == TaskStatus.CANCELLED
                completed = self.store.update(task_id, status=TaskStatus.CANCELLED if cancelled else TaskStatus.FAILED,
                    error=((current.error or 'Cancelled by user.') + '\nWorker later reported: ' + str(exc)) if cancelled else str(exc),
                    notification_kind='completion', attempt_id=attempt, observations=observations)
        else:
            with self._lock:
                current = self.store.get(task_id)
                completed = self.store.update(task_id, status=TaskStatus.CANCELLED if current.status == TaskStatus.CANCELLED else TaskStatus.SUCCEEDED,
                    progress=100, result_summary=result, notification_kind='completion', attempt_id=attempt, observations=observations)
        try:
            self._publish_progress(completed)
        finally:
            self._schedule_dependents(task_id)

    def _report_progress(self, task_id: str, progress: int) -> None:
        with self._lock:
            if self.store.get(task_id).status == TaskStatus.CANCELLED: return
            updated = self.store.update(task_id, progress=progress)
        self._publish_progress(updated)
        if progress >= 100:
            return
        mark = min((progress // 25) * 25, 75)
        with self._lock:
            if self.store.get(task_id).status == TaskStatus.CANCELLED: return
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
        self.store.enqueue_notification(task, kind=kind)

    def drain_notifications(self, user_id: str, limit: int = 3) -> list[dict[str, Any]]:
        """Return and remove completed task notifications for one user."""
        return self.store.drain_notifications(user_id, limit)

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
                TaskStatus.HELD,
            }
        ][:limit]

    def cancel(self, task_id: str, user_id: str | None = None) -> dict[str, Any]:
        with self._lock:
            task = self.store.get(task_id, user_id=user_id)
            if task.status in TERMINAL_STATUSES:
                return task.as_dict()
            future = self._futures.get(task_id)
            if future is not None: future.cancel()
            attempt = self._attempts.get(task_id)
            unused = attempt if attempt and self.store.attempt(attempt, task.user_id)['phase'] == 'admitted' else None
            return self.store.update(task_id, status=TaskStatus.CANCELLED, error="Cancelled by user.", notification_kind='completion', attempt_id=unused).as_dict()

    def retry(self, task_id: str, user_id: str | None = None) -> dict[str, Any]:
        if self.control_gate: self.control_gate.checkpoint()
        task = self.store.get(task_id, user_id=user_id)
        if task.status not in {TaskStatus.FAILED, TaskStatus.CANCELLED, TaskStatus.HELD}:
            raise ValueError("Only failed, cancelled or held tasks can be retried.")
        future = self._futures.get(task_id)
        if future is not None and not future.done():
            raise RuntimeError('The previous task attempt is still draining; inspect its result before retrying.')
        if self.control_gate: self._task_epochs[task_id] = self.control_gate.epoch
        self.store.update(task_id, status=TaskStatus.PENDING, progress=0, error="", result_summary="")
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
