from __future__ import annotations

import threading
import uuid
from datetime import datetime, timezone
from typing import Any


class PresentationStore:
    """Authoritative in-process state for UI blocks and canvas scenes."""

    def __init__(self) -> None:
        self._blocks: dict[str, dict[str, Any]] = {}
        self._lock = threading.RLock()

    def upsert(self, block_type: str, payload: dict[str, Any]) -> dict[str, Any]:
        with self._lock:
            block_id = self._block_id(block_type, payload)
            block = {
                "block_id": block_id,
                "block_type": block_type,
                "visible": True,
                "updated_at": datetime.now(timezone.utc).isoformat(),
                **payload,
            }
            self._blocks[block_id] = block
            return dict(block)

    def close(self, block_id: str) -> bool:
        with self._lock:
            block = self._blocks.get(block_id)
            if block is None:
                return False
            block["visible"] = False
            block["updated_at"] = datetime.now(timezone.utc).isoformat()
            return True

    def get(self, block_id: str) -> dict[str, Any] | None:
        with self._lock:
            block = self._blocks.get(block_id)
            return dict(block) if block is not None else None

    def snapshot(self) -> dict[str, Any]:
        with self._lock:
            blocks = [dict(block) for block in self._blocks.values() if block.get("visible", True)]
            return {"blocks": blocks}

    def _block_id(self, block_type: str, payload: dict[str, Any]) -> str:
        for key in ("block_id", "progress_id", "scene_id", "action_id"):
            value = payload.get(key)
            if isinstance(value, str) and value.strip():
                return value.strip()
        return f"{block_type}-{uuid.uuid4().hex}"
