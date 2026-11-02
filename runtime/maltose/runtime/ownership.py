"""Ownership of native runtime state and its child workers."""
from __future__ import annotations

import fcntl
import os
from pathlib import Path
import subprocess
import sys
import threading


class RuntimeLease:
    """Kernel-held lease; a leftover lock file is never evidence of a live process."""
    def __init__(self, directory: Path):
        directory.mkdir(parents=True, exist_ok=True, mode=0o700)
        descriptor = os.open(directory / '.native-runtime.lock', os.O_RDWR | os.O_CREAT | os.O_NOFOLLOW, 0o600)
        self.stream = os.fdopen(descriptor, 'r+')
        try:
            fcntl.flock(descriptor, fcntl.LOCK_EX | fcntl.LOCK_NB)
            self.stream.truncate(0)
            self.stream.write(str(os.getpid()))
            self.stream.flush()
        except BaseException:
            self.stream.close()
            raise RuntimeError('Another Maltose native runtime owns this configuration; close it before starting another') from None

    def close(self):
        self.stream.close()

    def __enter__(self): return self
    def __exit__(self, *_): self.close()


class ManagedWorker:
    """Child observes its private stdin EOF if the runtime crashes or exits."""
    def __init__(self, module: str, arguments: list[str], *, on_unexpected_exit=None):
        self._closing = threading.Event()
        self.process = subprocess.Popen(
            [sys.executable, '-m', 'maltose.runtime.worker', module, *arguments],
            stdin=subprocess.PIPE, stdout=sys.stderr, stderr=sys.stderr,
        )
        if on_unexpected_exit is not None:
            def observe():
                code = self.process.wait()
                if not self._closing.is_set(): on_unexpected_exit(code)
            threading.Thread(target=observe, name='maltose-worker-monitor', daemon=True).start()

    def close(self):
        self._closing.set()
        if self.process.stdin is not None: self.process.stdin.close()
        try:
            self.process.wait(timeout=5)
        except subprocess.TimeoutExpired:
            self.process.terminate()
            try: self.process.wait(timeout=2)
            except subprocess.TimeoutExpired:
                self.process.kill()
                self.process.wait(timeout=2)
