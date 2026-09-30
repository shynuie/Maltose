from __future__ import annotations

import os
import select
import subprocess
import sys
from pathlib import Path

from myagent.kws_protocol import ERROR, HEALTH, PCM, READY, RESET, RESPONSE, SHUTDOWN, json_bytes, parse_json, read_message, write_message
from myagent.voice.wake import WakeWordDetector, WakeWordHit


class AlibabaKWSProcessError(RuntimeError):
    pass


class AlibabaKWSDetector:
    """Python 3.12-side adapter for the isolated Alibaba KWS worker."""

    def __init__(
        self,
        model_dir: str | Path,
        *,
        python: str | Path,
        worker_script: str | Path | None = None,
        sample_rate: int = 16000,
        timeout_seconds: float = 20.0,
    ) -> None:
        self.model_dir = Path(model_dir).expanduser()
        self.python = str(python)
        self.sample_rate = sample_rate
        self.timeout_seconds = timeout_seconds
        script = Path(worker_script or Path(__file__).with_name("alibaba_kws_worker.py"))
        env = os.environ.copy()
        env["PYTHONPATH"] = str(Path(__file__).resolve().parents[2]) + os.pathsep + env.get("PYTHONPATH", "")
        self._process = subprocess.Popen(
            [self.python, str(script), "--model-dir", str(self.model_dir)],
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=None,
            env=env,
        )
        assert self._process.stdin is not None
        assert self._process.stdout is not None
        self._stdin = self._process.stdin
        self._stdout = self._process.stdout
        message = self._read_message_with_timeout()
        if message is None or message[0] != READY:
            self.close()
            raise AlibabaKWSProcessError("Alibaba KWS worker did not become ready")

    def process_frame(self, pcm_frame: bytes, sample_rate: int) -> WakeWordHit | None:
        if sample_rate != self.sample_rate:
            raise ValueError(f"Alibaba KWS requires {self.sample_rate}Hz audio")
        write_message(self._stdin, PCM, pcm_frame)
        kind, payload = self._read_response()
        if kind != RESPONSE:
            return None
        data = parse_json(payload)
        hit = data.get("hit")
        return WakeWordHit(keyword=str(hit["keyword"])) if hit else None

    def reset(self) -> None:
        write_message(self._stdin, RESET)
        self._read_response()

    def health(self) -> dict:
        write_message(self._stdin, HEALTH)
        kind, payload = self._read_response()
        if kind != RESPONSE:
            raise AlibabaKWSProcessError(parse_json(payload).get("error", "worker error"))
        return parse_json(payload)

    def close(self) -> None:
        if getattr(self, "_process", None) is None:
            return
        try:
            if self._process.poll() is None:
                write_message(self._stdin, SHUTDOWN)
                self._process.wait(timeout=3)
        except (BrokenPipeError, OSError, subprocess.TimeoutExpired):
            self._process.kill()
        finally:
            self._process = None

    def _read_response(self) -> tuple[int, bytes]:
        message = self._read_message_with_timeout()
        if message is None:
            raise AlibabaKWSProcessError("Alibaba KWS worker exited")
        if message[0] == ERROR:
            raise AlibabaKWSProcessError(parse_json(message[1]).get("error", "worker error"))
        return message

    def _read_message_with_timeout(self) -> tuple[int, bytes] | None:
        ready, _, _ = select.select([self._stdout], [], [], self.timeout_seconds)
        if not ready:
            self.close()
            raise AlibabaKWSProcessError(
                f"Alibaba KWS worker response timed out after {self.timeout_seconds:.1f}s"
            )
        return read_message(self._stdout)

    def __del__(self) -> None:
        self.close()
