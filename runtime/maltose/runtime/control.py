"""Cooperative execution ownership shared by native conversation/tools/workers.

Pausing closes dispatch atomically, then drains already admitted activities.
It never blocks the IPC reader waiting for a tool that needs that same reader.
"""
from __future__ import annotations

from collections import Counter
from contextlib import contextmanager
import threading
import uuid


class AutonomyPaused(RuntimeError):
    """A new autonomous action was not admitted; no handler was executed."""


class AutonomyControl:
    def __init__(self, publisher=None):
        self._lock = threading.RLock()
        self._state = 'active'
        self._owner = None
        self._lease = None
        self._epoch = 0
        self._version = 0
        self._activities = {}
        self._publisher = publisher

    @property
    def epoch(self):
        with self._lock: return self._epoch

    @property
    def active(self):
        with self._lock: return self._state == 'active'

    def snapshot(self):
        with self._lock:
            return dict(state=self._state, ownerID=self._owner, leaseID=self._lease,
                        epoch=self._epoch, version=self._version,
                        activities=dict(Counter(self._activities.values())), inFlight=len(self._activities))

    def checkpoint(self, expected_epoch=None):
        with self._lock:
            if self._state != 'active' or (expected_epoch is not None and expected_epoch != self._epoch):
                raise AutonomyPaused('Maltose autonomy is suspended for control handoff')

    @contextmanager
    def activity(self, kind, *, expected_epoch=None):
        token = uuid.uuid4().hex
        with self._lock:
            self.checkpoint(expected_epoch)
            self._activities[token] = kind
        try:
            yield
        finally:
            update = None
            with self._lock:
                self._activities.pop(token)
                if self._state == 'pausing':
                    if not self._activities: self._state = 'paused'
                    self._version += 1; update = self.snapshot()
            self._publish(update)

    def pause(self, owner_id):
        if not isinstance(owner_id, str) or not owner_id or len(owner_id) > 128:
            raise ValueError('A bounded control ownerID is required')
        with self._lock:
            if self._state == 'closed': raise RuntimeError('Autonomy control is closed')
            if self._state != 'active':
                if self._owner != owner_id: raise RuntimeError('Autonomy is held by another controller')
                return self.snapshot()
            self._owner = owner_id; self._lease = uuid.uuid4().hex
            self._epoch += 1; self._version += 1
            self._state = 'pausing' if self._activities else 'paused'
            snapshot = self.snapshot()
        self._publish(snapshot)
        return snapshot

    def resume(self, owner_id, lease_id, *, intent_confirmed=False, before_resume=None):
        with self._lock:
            if self._state != 'paused' or self._activities:
                raise RuntimeError('Autonomy has not finished draining')
            if not self._owner or self._owner != owner_id or self._lease != lease_id:
                raise PermissionError('Control lease does not belong to this owner')
            if intent_confirmed is not True:
                raise PermissionError('A new user intent is required before resuming autonomy')
            if before_resume: before_resume()
            self._state = 'active'; self._owner = None; self._lease = None
            self._epoch += 1; self._version += 1
            snapshot = self.snapshot()
        self._publish(snapshot)
        return snapshot

    def close(self):
        with self._lock:
            if self._state == 'closed': return
            self._state = 'closed'; self._epoch += 1; self._version += 1
            snapshot = self.snapshot()
        self._publish(snapshot)

    def _publish(self, snapshot):
        if snapshot is not None and self._publisher:
            self._publisher('autonomy_state', snapshot)
