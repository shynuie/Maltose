from __future__ import annotations

import json
import threading
import unittest
from urllib.request import Request, urlopen

from myagent.runtime import EventHub
from myagent.web import WebServer


class WebServerTest(unittest.TestCase):
    def setUp(self) -> None:
        self.hub = EventHub()
        self.inputs: list[str] = []
        self.actions: list[tuple[str, object]] = []
        self.server = WebServer(
            self.hub,
            input_handler=self.inputs.append,
            action_handler=lambda action_id, value: self.actions.append((action_id, value)),
            state_provider=lambda: {"state": "thinking"},
            port=0,
        )
        self.server.start()
        host, port = self.server.address
        self.base_url = f"http://{host}:{port}"

    def tearDown(self) -> None:
        self.server.close()

    def test_serves_index_and_state(self) -> None:
        with urlopen(self.base_url + "/") as response:
            self.assertIn("MyAgent", response.read().decode("utf-8"))
        with urlopen(self.base_url + "/api/state") as response:
            self.assertEqual(json.loads(response.read()), {"state": "thinking"})

    def test_accepts_text_input(self) -> None:
        request = Request(
            self.base_url + "/api/input",
            data=json.dumps({"text": "打开窗帘"}).encode("utf-8"),
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        with urlopen(request) as response:
            self.assertEqual(response.status, 202)
        self.assertEqual(self.inputs, ["打开窗帘"])

    def test_accepts_ui_action(self) -> None:
        request = Request(
            self.base_url + "/api/action",
            data=json.dumps({"action_id": "confirm", "value": {"job": 1}}).encode("utf-8"),
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        with urlopen(request) as response:
            self.assertEqual(response.status, 202)
        self.assertEqual(self.actions, [("confirm", {"job": 1})])

    def test_sse_stream_delivers_event(self) -> None:
        result: list[bytes] = []
        connected = threading.Event()

        def read_stream() -> None:
            request = Request(self.base_url + "/api/events")
            with urlopen(request, timeout=2) as response:
                result.append(response.readline())
                connected.set()
                result.append(response.readline())
                result.append(response.readline())
                result.append(response.readline())

        thread = threading.Thread(target=read_stream)
        thread.start()
        # The first line is the connection comment; publishing completes the reader.
        self.assertTrue(connected.wait(timeout=2))
        self.hub.publish("assistant_message", {"content": "完成"})
        thread.join(timeout=2)

        self.assertFalse(thread.is_alive())
        self.assertIn(b"event: assistant_message", b"".join(result))
        self.assertIn("完成".encode("utf-8"), b"".join(result))
