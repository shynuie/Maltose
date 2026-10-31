"""Indexing job and queue contracts.

This module deliberately contains no worker thread.  It defines the state
transitions that a polling watcher or a future background service can rely on.
The in-memory implementation is sufficient for the first in-process worker
and can later be replaced by a durable queue without changing callers.
"""

from __future__ import annotations

import logging
import json
import sqlite3
import threading
import uuid
from collections import deque
from dataclasses import dataclass, field
from datetime import datetime
from enum import StrEnum
from pathlib import Path
from typing import Protocol

from myagent.knowledge.indexer import IndexResult
from myagent.knowledge.models import ScannedFile

logger = logging.getLogger(__name__)


class IndexJobStatus(StrEnum):
    QUEUED = "queued"
    RUNNING = "running"
    SUCCEEDED = "succeeded"
    FAILED = "failed"


@dataclass
class IndexJob:
    job_id: str
    scanned_file: ScannedFile
    max_attempts: int = 3
    attempts: int = 0
    status: IndexJobStatus = IndexJobStatus.QUEUED
    result: IndexResult | None = None
    last_error: str | None = None
    error_history: list[str] = field(default_factory=list)


class IndexingQueue(Protocol):
    def enqueue(self, scanned_file: ScannedFile, *, max_attempts: int = 3) -> IndexJob:
        """Add a document indexing job and return its job record."""

    def claim(self) -> IndexJob | None:
        """Atomically claim the oldest queued job for a worker."""

    def complete(self, job_id: str, result: IndexResult) -> IndexJob:
        """Mark a claimed job as successfully indexed."""

    def fail(self, job_id: str, error: Exception | str) -> IndexJob:
        """Record an error and retry or permanently fail the job."""

    def get(self, job_id: str) -> IndexJob | None:
        """Return the current job state, if it exists."""

    def list_jobs(self, *, status: IndexJobStatus | None = None) -> list[IndexJob]:
        """Return jobs ordered from oldest to newest."""


class InMemoryIndexingQueue:
    """Thread-safe FIFO queue with bounded automatic retries."""

    def __init__(self) -> None:
        self._jobs: dict[str, IndexJob] = {}
        self._pending: deque[str] = deque()
        self._lock = threading.RLock()

    def enqueue(self, scanned_file: ScannedFile, *, max_attempts: int = 3) -> IndexJob:
        if max_attempts < 1:
            raise ValueError("max_attempts must be at least 1")
        job = IndexJob(
            job_id=f"index-{uuid.uuid4().hex}",
            scanned_file=scanned_file,
            max_attempts=max_attempts,
        )
        with self._lock:
            self._jobs[job.job_id] = job
            self._pending.append(job.job_id)
        logger.info("kdb_index_job_enqueued job_id=%s path=%s", job.job_id, scanned_file.path)
        return job

    def claim(self) -> IndexJob | None:
        with self._lock:
            while self._pending:
                job = self._jobs[self._pending.popleft()]
                if job.status != IndexJobStatus.QUEUED:
                    continue
                job.status = IndexJobStatus.RUNNING
                job.attempts += 1
                logger.info(
                    "kdb_index_job_claimed job_id=%s attempt=%d/%d",
                    job.job_id,
                    job.attempts,
                    job.max_attempts,
                )
                return job
        return None

    def complete(self, job_id: str, result: IndexResult) -> IndexJob:
        with self._lock:
            job = self._require(job_id)
            self._require_status(job, IndexJobStatus.RUNNING)
            job.result = result
            job.status = IndexJobStatus.SUCCEEDED
            logger.info("kdb_index_job_succeeded job_id=%s", job_id)
            return job

    def fail(self, job_id: str, error: Exception | str) -> IndexJob:
        message = str(error)
        with self._lock:
            job = self._require(job_id)
            self._require_status(job, IndexJobStatus.RUNNING)
            job.last_error = message
            job.error_history.append(message)
            if job.attempts < job.max_attempts:
                job.status = IndexJobStatus.QUEUED
                self._pending.append(job.job_id)
                logger.warning(
                    "kdb_index_job_retry job_id=%s attempt=%d/%d error=%s",
                    job.job_id,
                    job.attempts,
                    job.max_attempts,
                    message,
                )
            else:
                job.status = IndexJobStatus.FAILED
                logger.error("kdb_index_job_failed job_id=%s error=%s", job.job_id, message)
            return job

    def get(self, job_id: str) -> IndexJob | None:
        with self._lock:
            return self._jobs.get(job_id)

    def list_jobs(self, *, status: IndexJobStatus | None = None) -> list[IndexJob]:
        with self._lock:
            jobs = list(self._jobs.values())
            if status is not None:
                jobs = [job for job in jobs if job.status == status]
            return jobs

    def _require(self, job_id: str) -> IndexJob:
        try:
            return self._jobs[job_id]
        except KeyError as exc:
            raise KeyError(f"Unknown indexing job: {job_id}") from exc

    @staticmethod
    def _require_status(job: IndexJob, expected: IndexJobStatus) -> None:
        if job.status != expected:
            raise ValueError(
                f"Job {job.job_id} is {job.status.value}; expected {expected.value}"
            )


class SQLiteIndexingQueue:
    """Durable queue that recovers interrupted jobs after process restart."""

    def __init__(self, path: str | Path) -> None:
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._lock = threading.RLock()
        self._connection = sqlite3.connect(self.path, check_same_thread=False)
        self._connection.row_factory = sqlite3.Row
        self._initialize()

    def close(self) -> None:
        with self._lock:
            self._connection.close()

    def _initialize(self) -> None:
        with self._lock:
            self._connection.execute(
                """
                CREATE TABLE IF NOT EXISTS indexing_jobs (
                    job_id TEXT PRIMARY KEY,
                    path TEXT NOT NULL,
                    relative_path TEXT NOT NULL,
                    filename TEXT NOT NULL,
                    file_type TEXT NOT NULL,
                    content_hash TEXT NOT NULL,
                    file_size INTEGER NOT NULL,
                    modified_at TEXT NOT NULL,
                    max_attempts INTEGER NOT NULL,
                    attempts INTEGER NOT NULL,
                    status TEXT NOT NULL,
                    result_json TEXT,
                    last_error TEXT,
                    error_history_json TEXT NOT NULL DEFAULT '[]',
                    created_at TEXT NOT NULL
                )
                """
            )
            self._connection.execute(
                "UPDATE indexing_jobs SET status = 'queued' WHERE status = 'running' AND attempts < max_attempts"
            )
            self._connection.execute(
                "UPDATE indexing_jobs SET status = 'failed', last_error = COALESCE(last_error, 'worker interrupted') "
                "WHERE status = 'running' AND attempts >= max_attempts"
            )
            self._connection.commit()

    def enqueue(self, scanned_file: ScannedFile, *, max_attempts: int = 3) -> IndexJob:
        if max_attempts < 1:
            raise ValueError("max_attempts must be at least 1")
        job = IndexJob(
            job_id=f"index-{uuid.uuid4().hex}",
            scanned_file=scanned_file,
            max_attempts=max_attempts,
        )
        with self._lock:
            self._connection.execute(
                """
                INSERT INTO indexing_jobs (
                    job_id, path, relative_path, filename, file_type, content_hash,
                    file_size, modified_at, max_attempts, attempts, status,
                    error_history_json, created_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, 0, 'queued', '[]', ?)
                """,
                (
                    job.job_id,
                    str(scanned_file.path),
                    scanned_file.relative_path,
                    scanned_file.filename,
                    scanned_file.file_type,
                    scanned_file.content_hash,
                    scanned_file.file_size,
                    scanned_file.modified_at.isoformat(),
                    max_attempts,
                    datetime.now().astimezone().isoformat(),
                ),
            )
            self._connection.commit()
        return job

    def claim(self) -> IndexJob | None:
        with self._lock:
            self._connection.execute("BEGIN IMMEDIATE")
            row = self._connection.execute(
                "SELECT * FROM indexing_jobs WHERE status = 'queued' ORDER BY created_at, job_id LIMIT 1"
            ).fetchone()
            if row is None:
                self._connection.commit()
                return None
            self._connection.execute(
                "UPDATE indexing_jobs SET status = 'running', attempts = attempts + 1 WHERE job_id = ?",
                (row["job_id"],),
            )
            self._connection.commit()
            row = self._connection.execute(
                "SELECT * FROM indexing_jobs WHERE job_id = ?", (row["job_id"],)
            ).fetchone()
            return self._row_to_job(row)

    def complete(self, job_id: str, result: IndexResult) -> IndexJob:
        with self._lock:
            row = self._require_row(job_id)
            self._require_status(row, IndexJobStatus.RUNNING)
            self._connection.execute(
                "UPDATE indexing_jobs SET status = 'succeeded', result_json = ? WHERE job_id = ?",
                (json.dumps(result.__dict__), job_id),
            )
            self._connection.commit()
            return self._row_to_job(self._require_row(job_id))

    def fail(self, job_id: str, error: Exception | str) -> IndexJob:
        with self._lock:
            row = self._require_row(job_id)
            self._require_status(row, IndexJobStatus.RUNNING)
            history = json.loads(row["error_history_json"])
            history.append(str(error))
            status = "queued" if row["attempts"] < row["max_attempts"] else "failed"
            self._connection.execute(
                "UPDATE indexing_jobs SET status = ?, last_error = ?, error_history_json = ? WHERE job_id = ?",
                (status, str(error), json.dumps(history), job_id),
            )
            self._connection.commit()
            return self._row_to_job(self._require_row(job_id))

    def get(self, job_id: str) -> IndexJob | None:
        with self._lock:
            row = self._connection.execute(
                "SELECT * FROM indexing_jobs WHERE job_id = ?", (job_id,)
            ).fetchone()
            return self._row_to_job(row) if row else None

    def list_jobs(self, *, status: IndexJobStatus | None = None) -> list[IndexJob]:
        with self._lock:
            if status is None:
                rows = self._connection.execute(
                    "SELECT * FROM indexing_jobs ORDER BY created_at, job_id"
                ).fetchall()
            else:
                rows = self._connection.execute(
                    "SELECT * FROM indexing_jobs WHERE status = ? ORDER BY created_at, job_id",
                    (status.value,),
                ).fetchall()
            return [self._row_to_job(row) for row in rows]

    def _require_row(self, job_id: str) -> sqlite3.Row:
        row = self._connection.execute(
            "SELECT * FROM indexing_jobs WHERE job_id = ?", (job_id,)
        ).fetchone()
        if row is None:
            raise KeyError(f"Unknown indexing job: {job_id}")
        return row

    @staticmethod
    def _require_status(row: sqlite3.Row, expected: IndexJobStatus) -> None:
        if row["status"] != expected.value:
            raise ValueError(f"Job {row['job_id']} is {row['status']}; expected {expected.value}")

    @staticmethod
    def _row_to_job(row: sqlite3.Row) -> IndexJob:
        scanned = ScannedFile(
            path=Path(row["path"]),
            relative_path=row["relative_path"],
            filename=row["filename"],
            file_type=row["file_type"],
            content_hash=row["content_hash"],
            file_size=row["file_size"],
            modified_at=datetime.fromisoformat(row["modified_at"]),
        )
        raw_result = json.loads(row["result_json"]) if row["result_json"] else None
        return IndexJob(
            job_id=row["job_id"],
            scanned_file=scanned,
            max_attempts=row["max_attempts"],
            attempts=row["attempts"],
            status=IndexJobStatus(row["status"]),
            result=IndexResult(**raw_result) if raw_result else None,
            last_error=row["last_error"],
            error_history=json.loads(row["error_history_json"]),
        )
