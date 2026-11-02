"""Small thread-safe runtime counters for filesystem/KDB integration."""

from __future__ import annotations

import threading
from collections import Counter
from typing import Any


class FilesystemRuntimeMetrics:
    def __init__(self) -> None:
        self._counts: Counter[str] = Counter()
        self._lock = threading.Lock()

    def increment(self, name: str, amount: int = 1) -> None:
        with self._lock:
            self._counts[name] += amount

    def snapshot(self) -> dict[str, int]:
        with self._lock:
            return dict(self._counts)

    def as_dict(self) -> dict[str, Any]:
        return {"counters": self.snapshot()}
