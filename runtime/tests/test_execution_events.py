from __future__ import annotations

import unittest

from maltose.execution.events import ExecutionEvent, ExecutionEventType, publish_to_event_hub
from maltose.runtime import EventHub


class ExecutionEventTests(unittest.TestCase):
    def test_publisher_adapts_typed_event_to_shared_event_hub(self) -> None:
        hub = EventHub()
        subscription = hub.subscribe()
        publish_to_event_hub(hub)(ExecutionEvent(
            ExecutionEventType.RUNNING, "execution-1", {"backend": "docker"}
        ))
        event = next(subscription)
        self.assertEqual(event.type, "execution.running")
        self.assertEqual(event.payload["execution_id"], "execution-1")
        self.assertEqual(event.payload["backend"], "docker")
        subscription.close()


if __name__ == "__main__":
    unittest.main()
