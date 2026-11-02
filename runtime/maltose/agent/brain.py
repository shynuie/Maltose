from __future__ import annotations

import json
import os
import urllib.error
import urllib.request
from dataclasses import dataclass
from typing import Protocol


@dataclass(frozen=True)
class TurnContext:
    user_id: str | None = None
    speaker_score: float | None = None
    speaker_status: str = "unknown"
    input_source: str | None = None
    response_format: str | None = None
    input_id: str | None = None


class AgentBrain(Protocol):
    """Abstract protocol for agent thinking / response generation."""

    def process(self, user_text: str, context: TurnContext | None = None) -> str:
        """Process user text and return the response text to speak."""
        ...


class EchoBrain:
    """Minimal brain for Phase 1 that echoes the transcribed text."""

    def __init__(self, prefix: str = "收到，你說：") -> None:
        self._prefix = prefix

    def process(self, user_text: str, context: TurnContext | None = None) -> str:
        return f"{self._prefix}{user_text}"


class OpenClawBrain:
    """Agent brain backed by OpenClaw's OpenAI-compatible Gateway endpoint."""

    def __init__(
        self,
        endpoint: str = "http://127.0.0.1:18789/v1/chat/completions",
        token: str | None = None,
        model: str = "openclaw/default",
        session_id: str = "myagent-voice",
        timeout: float = 120.0,
    ) -> None:
        self.endpoint = endpoint
        self.token = token or os.environ.get("OPENCLAW_GATEWAY_TOKEN")
        self.model = model
        self.session_id = session_id
        self.timeout = timeout

    def process(self, user_text: str, context: TurnContext | None = None) -> str:
        text = user_text.strip()
        if not text:
            raise ValueError("OpenClaw brain input cannot be empty.")

        payload = json.dumps(
            {
                "model": self.model,
                "user": self.session_id,
                "stream": False,
                "messages": [{"role": "user", "content": text}],
            }
        ).encode("utf-8")
        headers = {"Content-Type": "application/json"}
        if self.token:
            headers["Authorization"] = f"Bearer {self.token}"

        request = urllib.request.Request(
            self.endpoint,
            data=payload,
            headers=headers,
            method="POST",
        )
        try:
            with urllib.request.urlopen(request, timeout=self.timeout) as response:
                body = json.loads(response.read().decode("utf-8"))
        except urllib.error.HTTPError as exc:
            detail = exc.read().decode("utf-8", errors="replace")
            raise RuntimeError(
                f"OpenClaw Gateway returned HTTP {exc.code}: {detail[:500]}"
            ) from exc
        except urllib.error.URLError as exc:
            raise RuntimeError(
                f"Could not connect to OpenClaw Gateway at {self.endpoint}: {exc.reason}"
            ) from exc

        try:
            content = body["choices"][0]["message"]["content"]
        except (KeyError, IndexError, TypeError) as exc:
            raise RuntimeError("OpenClaw response did not contain assistant content.") from exc

        if isinstance(content, list):
            content = "".join(
                part.get("text", "")
                for part in content
                if isinstance(part, dict)
            )
        if not isinstance(content, str) or not content.strip():
            raise RuntimeError("OpenClaw returned an empty assistant response.")
        return content.strip()
