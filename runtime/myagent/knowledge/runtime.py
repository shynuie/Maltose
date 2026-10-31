"""In-process runtime that connects watching, dispatching, and indexing."""

from __future__ import annotations

import logging
import threading
from dataclasses import dataclass

from myagent.knowledge.event_dispatcher import DocumentEventDispatcher, DocumentEventResult
from myagent.knowledge.queue import IndexingQueue
from myagent.knowledge.watcher import DocumentWatcher
from myagent.knowledge.worker import IndexingWorker

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class RuntimeCycleResult:
    events: tuple[object, ...]
    dispatched: tuple[DocumentEventResult, ...]
    worker_attempts: int


class KnowledgeRuntime:
    """Coordinate the local KDB event-to-indexing pipeline."""

    def __init__(
        self,
        *,
        watcher: DocumentWatcher,
        dispatcher: DocumentEventDispatcher,
        queue: IndexingQueue,
        worker: IndexingWorker,
        poll_interval: float = 1.0,
    ) -> None:
        if poll_interval <= 0:
            raise ValueError("poll_interval must be positive")
        self.watcher = watcher
        self.dispatcher = dispatcher
        self.queue = queue
        self.worker = worker
        self.poll_interval = poll_interval
        self._stop_event = threading.Event()
        self._thread: threading.Thread | None = None

    def poll_once(self) -> RuntimeCycleResult:
        """Poll source changes, dispatch them, and synchronously drain jobs."""
        events = self.watcher.poll()
        dispatched = tuple(self.dispatcher.dispatch(event) for event in events)
        attempts = self.worker.run_until_empty()
        if events or attempts:
            logger.info(
                "kdb_runtime_cycle events=%d dispatched=%d worker_attempts=%d",
                len(events),
                len(dispatched),
                attempts,
            )
        else:
            logger.debug("kdb_runtime_cycle_empty")
        return RuntimeCycleResult(events, dispatched, attempts)

    def start(self) -> None:
        """Start the watcher and indexing worker in the current process."""
        if self._thread is not None and self._thread.is_alive():
            return
        self.watcher.start()
        self.worker.start()
        self._stop_event.clear()
        self._thread = threading.Thread(
            target=self._run_loop,
            name="myagent-kdb-runtime",
            daemon=True,
        )
        self._thread.start()
        logger.info("kdb_runtime_started")

    def stop(self, *, timeout: float | None = 5.0) -> None:
        """Stop polling and indexing, waiting for both to finish."""
        self._stop_event.set()
        if self._thread is not None:
            self._thread.join(timeout=timeout)
            if self._thread.is_alive():
                raise TimeoutError("Knowledge runtime did not stop before timeout")
            self._thread = None
        self.watcher.stop()
        self.worker.stop(timeout=timeout)
        logger.info("kdb_runtime_stopped")

    def _run_loop(self) -> None:
        while not self._stop_event.is_set():
            try:
                self.poll_once()
            except Exception:
                logger.exception("kdb_runtime_cycle_failed")
            self._stop_event.wait(self.poll_interval)
