from __future__ import annotations

import os
import select
import shutil
import subprocess
import sys
import threading
import time
from pathlib import Path

from maltose.kws_protocol import ERROR, HEADER, HEALTH, PCM, READY, RESET, RESPONSE, SHUTDOWN, parse_json, write_message
from maltose.voice.wake import WakeWordDetector, WakeWordHit


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
        startup_timeout_seconds: float = 60.0,
    ) -> None:
        self.model_dir = Path(model_dir).expanduser()
        self.python = str(Path(python).expanduser())
        self._io_lock = threading.RLock()
        self._process = None
        if shutil.which(self.python) is None:
            raise AlibabaKWSProcessError(
                f"找不到可執行的喚醒詞 Python：{self.python}。"
                "請在 Maltose 專案執行 uv run --no-sync python dev/tools/setup_kws_runtime.py，"
                "並將 wake.toml 的 wake.alibaba.python 設為 .venvs/kws310/bin/python。"
            )
        self.sample_rate = sample_rate
        self.timeout_seconds = timeout_seconds
        self.startup_timeout_seconds = startup_timeout_seconds
        script = Path(worker_script or Path(__file__).with_name("alibaba_kws_worker.py"))
        env = os.environ.copy()
        env["PYTHONPATH"] = str(Path(__file__).resolve().parents[2]) + os.pathsep + env.get("PYTHONPATH", "")
        try:
            self._process = subprocess.Popen(
                [self.python, str(script), "--model-dir", str(self.model_dir)],
                stdin=subprocess.PIPE,
                stdout=subprocess.PIPE,
                stderr=None,
                env=env,
                bufsize=0,
            )
        except OSError as error:
            raise AlibabaKWSProcessError(
                f"無法啟動喚醒詞 Python：{self.python}（{error.strerror}）。"
                "請執行 uv run --no-sync python dev/tools/setup_kws_runtime.py 重建隔離環境。"
            ) from error
        assert self._process.stdin is not None
        assert self._process.stdout is not None
        self._stdin = self._process.stdin
        self._stdout = self._process.stdout
        try:
            message = self._read_message_with_timeout(self.startup_timeout_seconds)
            if message is None or message[0] != READY:
                detail = parse_json(message[1]).get("error", "") if message and message[0] == ERROR else "worker exited before READY"
                raise AlibabaKWSProcessError(f"Alibaba KWS worker did not become ready: {detail}")
        except BaseException:
            self.close()
            raise

    def process_frame(self, pcm_frame: bytes, sample_rate: int) -> WakeWordHit | None:
        if sample_rate != self.sample_rate:
            raise ValueError(f"Alibaba KWS requires {self.sample_rate}Hz audio")
        kind, payload = self._request(PCM, pcm_frame)
        if kind != RESPONSE:
            return None
        data = parse_json(payload)
        hit = data.get("hit")
        return WakeWordHit(keyword=str(hit["keyword"])) if hit else None

    def reset(self) -> None:
        self._request(RESET)

    def health(self) -> dict:
        kind, payload = self._request(HEALTH)
        if kind != RESPONSE:
            raise AlibabaKWSProcessError(parse_json(payload).get("error", "worker error"))
        return parse_json(payload)

    def close(self) -> None:
        lock = getattr(self, "_io_lock", None)
        if lock is None: return
        with lock:
            self._close()

    def _close(self) -> None:
        process = getattr(self, "_process", None)
        if process is None:
            return
        self._process = None
        try:
            if process.poll() is None:
                write_message(self._stdin, SHUTDOWN)
                process.wait(timeout=3)
        except (BrokenPipeError, OSError, subprocess.TimeoutExpired):
            process.kill()
            process.wait(timeout=3)
        finally:
            for stream in (process.stdin, process.stdout):
                if stream is not None:
                    stream.close()

    def _request(self, kind: int, payload: bytes = b"") -> tuple[int, bytes]:
        # Listening, device changes and shutdown may arrive from different threads.
        # Keep a complete write/read transaction together so replies cannot cross.
        with self._io_lock:
            if self._process is None or self._process.poll() is not None:
                raise AlibabaKWSProcessError("Alibaba KWS worker is closed")
            try:
                write_message(self._stdin, kind, payload)
                return self._read_response()
            except (BrokenPipeError, OSError, EOFError) as error:
                self._close()
                raise AlibabaKWSProcessError("Alibaba KWS worker communication failed") from error

    def _read_response(self) -> tuple[int, bytes]:
        message = self._read_message_with_timeout()
        if message is None:
            raise AlibabaKWSProcessError("Alibaba KWS worker exited")
        if message[0] == ERROR:
            raise AlibabaKWSProcessError(parse_json(message[1]).get("error", "worker error"))
        if message[0] != RESPONSE:
            self.close()
            raise AlibabaKWSProcessError("Unexpected Alibaba KWS response kind")
        return message

    def _read_message_with_timeout(self, timeout: float | None = None) -> tuple[int, bytes] | None:
        timeout = self.timeout_seconds if timeout is None else timeout
        deadline = time.monotonic() + timeout
        def exact(length: int, *, allow_eof: bool = False):
            chunks = bytearray()
            while len(chunks) < length:
                remaining = deadline - time.monotonic()
                ready, _, _ = select.select([self._stdout], [], [], max(0, remaining))
                if not ready or remaining <= 0:
                    self.close()
                    raise AlibabaKWSProcessError(f"Alibaba KWS worker response timed out after {timeout:.2f}s")
                chunk = os.read(self._stdout.fileno(), length - len(chunks))
                if not chunk:
                    if allow_eof and not chunks: return None
                    self.close()
                    raise AlibabaKWSProcessError("Incomplete Alibaba KWS response frame")
                chunks.extend(chunk)
            return bytes(chunks)
        header = exact(HEADER.size, allow_eof=True)
        if header is None: return None
        kind, length = HEADER.unpack(header)
        if kind not in (READY, RESPONSE, ERROR) or length > 1_048_576:
            self.close()
            raise AlibabaKWSProcessError("Invalid Alibaba KWS protocol frame")
        return kind, exact(length)

    def __del__(self) -> None:
        self.close()
