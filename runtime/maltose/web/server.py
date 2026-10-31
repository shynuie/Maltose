from __future__ import annotations

import json
import logging
import sys
import threading
from collections.abc import Callable
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any
from urllib.parse import urlsplit

from maltose.runtime import AgentEvent, EventHub

logger = logging.getLogger(__name__)

InputHandler = Callable[[str], None]
ActionHandler = Callable[[str, Any], None]
StateProvider = Callable[[], dict[str, Any]]


class WebServer:
    """Small local HTTP/SSE server for the Agent UI.

    The server deliberately depends on callbacks instead of Agent classes. This
    keeps the transport reusable for voice, CLI, and future runtime adapters.
    """

    def __init__(
        self,
        hub: EventHub,
        *,
        input_handler: InputHandler | None = None,
        action_handler: ActionHandler | None = None,
        state_provider: StateProvider | None = None,
        host: str = "127.0.0.1",
        port: int = 8765,
    ) -> None:
        self.hub = hub
        self.input_handler = input_handler
        self.action_handler = action_handler
        self.state_provider = state_provider or (lambda: {})
        self._server = _ThreadingHTTPServer(
            (host, port),
            _make_handler(self),
        )
        self._thread: threading.Thread | None = None

    @property
    def address(self) -> tuple[str, int]:
        host, port = self._server.server_address[:2]
        return str(host), int(port)

    def start(self) -> None:
        if self._thread is not None and self._thread.is_alive():
            return
        self._thread = threading.Thread(
            target=self._server.serve_forever,
            name="myagent-web-server",
            daemon=True,
        )
        self._thread.start()
        logger.info("web_server_started host=%s port=%s", *self.address)

    def close(self) -> None:
        if self._thread is None:
            return
        self._server.shutdown()
        self._server.server_close()
        if self._thread is not None:
            self._thread.join(timeout=2)
        self._thread = None

    def __enter__(self) -> WebServer:
        self.start()
        return self

    def __exit__(self, *_: object) -> None:
        self.close()


class _ThreadingHTTPServer(ThreadingHTTPServer):
    daemon_threads = True
    allow_reuse_address = True

    def handle_error(self, request: object, client_address: object) -> None:
        error = sys.exc_info()[1]
        if isinstance(error, (BrokenPipeError, ConnectionAbortedError, ConnectionResetError)):
            logger.debug('web_client_disconnected remote=%s error=%s', client_address, type(error).__name__)
            return
        super().handle_error(request, client_address)


def _make_handler(web_server: WebServer) -> type[BaseHTTPRequestHandler]:
    class Handler(BaseHTTPRequestHandler):
        server_version = "MaltoseWeb/0.1"

        def do_GET(self) -> None:  # noqa: N802 - required by BaseHTTPRequestHandler
            path = urlsplit(self.path).path
            if path == "/":
                self._send_static_index()
            elif path == "/api/state":
                self._send_json(HTTPStatus.OK, web_server.state_provider())
            elif path == "/api/events":
                self._stream_events()
            else:
                self._send_json(HTTPStatus.NOT_FOUND, {"error": "not_found"})

        def do_POST(self) -> None:  # noqa: N802 - required by BaseHTTPRequestHandler
            path = urlsplit(self.path).path
            if path == "/api/action":
                self._handle_action()
                return
            if path != "/api/input":
                self._send_json(HTTPStatus.NOT_FOUND, {"error": "not_found"})
                return
            if web_server.input_handler is None:
                self._send_json(HTTPStatus.SERVICE_UNAVAILABLE, {"error": "input_unavailable"})
                return
            try:
                length = int(self.headers.get("Content-Length", "0"))
                if length > 1024 * 1024:
                    raise ValueError("request body is too large")
                body = json.loads(self.rfile.read(length).decode("utf-8"))
                text = body.get("text") if isinstance(body, dict) else None
                if not isinstance(text, str) or not text.strip():
                    raise ValueError("text must be a non-empty string")
                web_server.input_handler(text.strip())
            except (UnicodeDecodeError, ValueError, json.JSONDecodeError) as exc:
                self._send_json(HTTPStatus.BAD_REQUEST, {"error": str(exc)})
                return
            except Exception:
                logger.exception("web_input_handler_failed")
                self._send_json(HTTPStatus.INTERNAL_SERVER_ERROR, {"error": "input_failed"})
                return
            self._send_json(HTTPStatus.ACCEPTED, {"accepted": True})

        def _handle_action(self) -> None:
            if web_server.action_handler is None:
                self._send_json(HTTPStatus.SERVICE_UNAVAILABLE, {"error": "actions_unavailable"})
                return
            try:
                length = int(self.headers.get("Content-Length", "0"))
                body = json.loads(self.rfile.read(length).decode("utf-8"))
                action_id = body.get("action_id") if isinstance(body, dict) else None
                value = body.get("value") if isinstance(body, dict) else None
                if not isinstance(action_id, str) or not action_id.strip():
                    raise ValueError("action_id must be a non-empty string")
                web_server.action_handler(action_id.strip(), value)
            except (UnicodeDecodeError, ValueError, json.JSONDecodeError) as exc:
                self._send_json(HTTPStatus.BAD_REQUEST, {"error": str(exc)})
                return
            self._send_json(HTTPStatus.ACCEPTED, {"accepted": True})

        def _send_static_index(self) -> None:
            index_path = Path(__file__).with_name("static") / "index.html"
            try:
                content = index_path.read_bytes()
            except OSError:
                self._send_json(HTTPStatus.INTERNAL_SERVER_ERROR, {"error": "ui_unavailable"})
                return
            self.send_response(HTTPStatus.OK)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.send_header("Content-Length", str(len(content)))
            self.end_headers()
            self.wfile.write(content)

        def _send_json(self, status: HTTPStatus, payload: dict[str, Any]) -> None:
            content = json.dumps(payload, ensure_ascii=False).encode("utf-8")
            self.send_response(status)
            self.send_header("Content-Type", "application/json; charset=utf-8")
            self.send_header("Content-Length", str(len(content)))
            self.end_headers()
            self.wfile.write(content)

        def _stream_events(self) -> None:
            subscription = web_server.hub.subscribe()
            self.send_response(HTTPStatus.OK)
            self.send_header("Content-Type", "text/event-stream; charset=utf-8")
            self.send_header("Cache-Control", "no-cache")
            self.send_header("Connection", "keep-alive")
            self.send_header("X-Accel-Buffering", "no")
            self.end_headers()
            try:
                self.wfile.write(b": connected\n\n")
                self.wfile.flush()
                for event in subscription:
                    content = json.dumps(event.as_dict(), ensure_ascii=False)
                    self.wfile.write(f"event: {event.type}\ndata: {content}\n\n".encode("utf-8"))
                    self.wfile.flush()
            except (BrokenPipeError, ConnectionResetError, OSError):
                logger.debug("web_event_stream_closed", exc_info=True)
            finally:
                subscription.close()

        def log_message(self, format: str, *args: object) -> None:
            logger.debug("web_http " + format, *args)

    return Handler
