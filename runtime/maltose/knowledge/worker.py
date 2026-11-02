"""Workers that consume indexing jobs and invoke the document indexer."""

from __future__ import annotations

import logging
import threading
from typing import Callable, Protocol

from maltose.knowledge.indexer import DocumentIndexer, IndexResult
from maltose.knowledge.queue import IndexJob, IndexingQueue

logger = logging.getLogger(__name__)


class Indexer(Protocol):
    def index(self, scanned_file) -> IndexResult:
        ...


class IndexingWorker:
    """Run indexing jobs synchronously or in a stoppable daemon thread."""

    def __init__(
        self,
        queue: IndexingQueue,
        indexer: Indexer | DocumentIndexer,
        *,
        idle_interval: float = 0.25,
        freshness_checker: Callable[[object], object | None] | None = None,
    ) -> None:
        if idle_interval <= 0:
            raise ValueError("idle_interval must be positive")
        self.queue = queue
        self.indexer = indexer
        self.idle_interval = idle_interval
        self.freshness_checker = freshness_checker
        self._stop_event = threading.Event()
        self._thread: threading.Thread | None = None

    def run_once(self) -> IndexJob | None:
        """Process one available job and return its updated state."""
        job = self.queue.claim()
        if job is None:
            return None
        try:
            scanned_file = job.scanned_file
            if self.freshness_checker is not None:
                scanned_file = self.freshness_checker(job.scanned_file)
                if scanned_file is None:
                    return self.queue.complete(
                        job.job_id,
                        IndexResult(job.scanned_file.relative_path, 0, "superseded"),
                    )
            result = self.indexer.index(scanned_file)
        except Exception as exc:
            return self.queue.fail(job.job_id, exc)
        return self.queue.complete(job.job_id, result)

    def run_until_empty(self, *, max_jobs: int | None = None) -> int:
        """Drain queued work and return the number of attempts performed."""
        if max_jobs is not None and max_jobs < 1:
            raise ValueError("max_jobs must be positive")
        attempts = 0
        while max_jobs is None or attempts < max_jobs:
            if self.run_once() is None:
                break
            attempts += 1
        return attempts

    def start(self) -> None:
        """Start the background worker; repeated starts are harmless."""
        if self._thread is not None and self._thread.is_alive():
            return
        self._stop_event.clear()
        self._thread = threading.Thread(
            target=self._run_loop,
            name="myagent-kdb-indexer",
            daemon=True,
        )
        self._thread.start()
        logger.info("kdb_index_worker_started")

    def stop(self, *, timeout: float | None = 5.0) -> None:
        """Request shutdown and optionally wait for the worker thread."""
        self._stop_event.set()
        if self._thread is not None:
            self._thread.join(timeout=timeout)
            if self._thread.is_alive():
                raise TimeoutError("Indexing worker did not stop before timeout")
            self._thread = None
        logger.info("kdb_index_worker_stopped")

    def _run_loop(self) -> None:
        while not self._stop_event.is_set():
            if self.run_once() is None:
                self._stop_event.wait(self.idle_interval)
