"""Small thread-safe execution runtime counters."""

from __future__ import annotations

import threading
from collections import Counter


class ExecutionRuntimeMetrics:
    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._counters: Counter[str] = Counter()

    def increment(self, name: str, amount: int = 1) -> None:
        if amount < 0:
            raise ValueError("Metric increment must not be negative.")
        with self._lock:
            self._counters[name] += amount

    def snapshot(self) -> dict[str, int]:
        with self._lock:
            return dict(self._counters)
