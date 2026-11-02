from __future__ import annotations

import threading
import unittest

from maltose.runtime import EventHub


class EventHubTest(unittest.TestCase):
    def test_publishes_serializable_events_to_subscribers(self) -> None:
        hub = EventHub()
        subscription = hub.subscribe()

        event = hub.publish("assistant_message", {"content": "你好"})

        self.assertEqual(next(subscription), event)
        self.assertEqual(event.as_dict()["payload"]["content"], "你好")
        subscription.close()

    def test_close_unblocks_waiting_subscriber(self) -> None:
        hub = EventHub()
        subscription = hub.subscribe()
        result: list[object] = []

        def consume() -> None:
            try:
                next(subscription)
            except StopIteration:
                result.append("closed")

        thread = threading.Thread(target=consume)
        thread.start()
        subscription.close()
        thread.join(timeout=1)

        self.assertFalse(thread.is_alive())
        self.assertEqual(result, ["closed"])

    def test_slow_subscriber_does_not_block_publisher(self) -> None:
        hub = EventHub(subscription_queue_size=1)
        subscription = hub.subscribe()

        hub.publish("state_changed", {"state": "thinking"})
        latest = hub.publish("state_changed", {"state": "speaking"})

        self.assertEqual(next(subscription), latest)
        subscription.close()

    def test_empty_event_type_is_rejected(self) -> None:
        with self.assertRaises(ValueError):
            EventHub().publish(" ")
