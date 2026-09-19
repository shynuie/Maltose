from __future__ import annotations

import platform
import subprocess
import threading
from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class TTSRequest:
    text: str
    voice: str | None = None
    rate: int | None = None
    output_path: Path | None = None


class MacOSSayTTS:
    """Text-to-speech provider backed by macOS `say`."""

    def __init__(self) -> None:
        self._process: subprocess.Popen[bytes] | None = None
        self._cancel_event: threading.Event | None = None
        self._lock = threading.RLock()

    def synthesize(self, request: TTSRequest) -> None:
        if platform.system() != "Darwin":
            raise RuntimeError("MacOSSayTTS only works on macOS.")

        text = request.text.strip()
        if not text:
            raise ValueError("TTS text cannot be empty.")

        command = ["say"]

        if request.voice:
            command.extend(["-v", request.voice])

        if request.rate is not None:
            command.extend(["-r", str(request.rate)])

        if request.output_path is not None:
            command.extend(["-o", str(request.output_path)])

        command.append(text)
        with self._lock:
            self.stop()
            process = subprocess.Popen(command)
            cancel_event = threading.Event()
            self._process = process
            self._cancel_event = cancel_event
        try:
            return_code = process.wait()
            if return_code != 0 and not cancel_event.is_set():
                raise subprocess.CalledProcessError(return_code, command)
        finally:
            with self._lock:
                if self._process is process:
                    self._process = None
                    self._cancel_event = None

    def stop(self) -> bool:
        """Stop the one active speech process. Returns whether one was running."""
        with self._lock:
            process = self._process
            if process is None or process.poll() is not None:
                self._process = None
                self._cancel_event = None
                return False
            if self._cancel_event is not None:
                self._cancel_event.set()
            process.terminate()
            self._process = None
            self._cancel_event = None
            return True
