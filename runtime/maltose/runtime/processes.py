"""OS-observed process ownership shared by native and Codex lifetime guards."""
from __future__ import annotations
from dataclasses import dataclass
import os
import signal
import time
import psutil


@dataclass(frozen=True)
class Identity:
    pid: int
    created: float

    @classmethod
    def read(cls, pid):
        process=psutil.Process(pid)
        return cls(pid,process.create_time())

    def process(self):
        try:
            process=psutil.Process(self.pid)
            return process if process.create_time()==self.created and process.status()!=psutil.STATUS_ZOMBIE else None
        except psutil.NoSuchProcess: return None


class Descendants:
    def __init__(self, root):
        self.root=root
        self.known={root.pid:root}
        self._protect_own_helpers=any(p.pid==root.pid for p in psutil.Process().parents())

    def collect(self):
        # Retain live descendants that have changed group or been reparented.
        self.known={pid:record for pid,record in self.known.items() if record.process() is not None}
        visited=set()
        # Private guard helpers perform resource cleanup outside the root scope.
        protected={os.getpid()}
        if self._protect_own_helpers:
            protected.update(p.pid for p in psutil.Process().children(recursive=True))
        for record in [self.root,*list(self.known.values())]:
            if record.pid in visited: continue
            visited.add(record.pid)
            process=record.process()
            if process is None: continue
            try: children=process.children(recursive=True)
            except psutil.NoSuchProcess: continue
            for child in children:
                visited.add(child.pid)
                if child.pid in protected: continue
                try:
                    if self._protect_own_helpers and any(p.pid==os.getpid() for p in child.parents()): continue
                    identity=Identity.read(child.pid)
                except psutil.NoSuchProcess: continue
                self.known[identity.pid]=identity
                if len(self.known)>8192: raise RuntimeError('Owned process tracking capacity exceeded')

    def stop(self, timeout=2, *, grace=.1, include_root=True):
        self.collect()
        deadline=time.monotonic()+timeout
        first=True
        terminate_until=time.monotonic()+grace
        while True:
            self.collect()
            for record in list(self.known.values()):
                if not include_root and record.pid==self.root.pid: continue
                process=record.process()
                if process is None: continue
                try: process.send_signal(signal.SIGTERM if time.monotonic()<terminate_until else signal.SIGKILL)
                except psutil.NoSuchProcess: pass
            if not any(record.process() is not None for record in self.known.values() if include_root or record.pid!=self.root.pid): return True
            if time.monotonic()>=deadline: return False
            time.sleep(.1 if first else .05); first=False

