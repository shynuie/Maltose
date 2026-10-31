from __future__ import annotations

import os
import select
import shutil
import subprocess
import sys
from pathlib import Path

from maltose.kws_protocol import ERROR, HEALTH, PCM, READY, RESET, RESPONSE, SHUTDOWN, json_bytes, parse_json, read_message, write_message
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

    def _read_response(self) -> tuple[int, bytes]:
        message = self._read_message_with_timeout()
        if message is None:
            raise AlibabaKWSProcessError("Alibaba KWS worker exited")
        if message[0] == ERROR:
            raise AlibabaKWSProcessError(parse_json(message[1]).get("error", "worker error"))
        return message

    def _read_message_with_timeout(self, timeout: float | None = None) -> tuple[int, bytes] | None:
        timeout = self.timeout_seconds if timeout is None else timeout
        ready, _, _ = select.select([self._stdout], [], [], timeout)
        if not ready:
            self.close()
            raise AlibabaKWSProcessError(
                f"Alibaba KWS worker response timed out after {timeout:.2f}s"
            )
        return read_message(self._stdout)

    def __del__(self) -> None:
        self.close()
