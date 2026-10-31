from __future__ import annotations

import platform
import os
import subprocess
import tempfile
import threading
import logging
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Protocol

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class TTSRequest:
    text: str
    voice: str | None = None
    rate: int | None = None
    output_path: Path | None = None


@dataclass(frozen=True)
class RenderedAudio:
    """A rendered audio artifact and whether the pipeline owns its cleanup."""

    path: Path
    cleanup_after_use: bool = True

    def cleanup(self) -> None:
        if self.cleanup_after_use:
            self.path.unlink(missing_ok=True)


class TTSAudioRenderer(Protocol):
    def render(self, request: TTSRequest) -> RenderedAudio:
        """Render speech without playing it."""

    def stop(self) -> bool:
        """Stop an active render operation, if any."""


class AudioPlayer(Protocol):
    def play(self, audio: RenderedAudio) -> None:
        """Play a rendered audio artifact to the default output device."""

    def stop(self) -> bool:
        """Stop active playback and return whether anything was playing."""


class MacOSSayAudioRenderer:
    """Render macOS speech to AIFF so playback can be prepared ahead of time."""

    def __init__(self) -> None:
        self._process: subprocess.Popen[bytes] | None = None
        self._cancel_event: threading.Event | None = None
        self._lock = threading.RLock()

    def render(self, request: TTSRequest) -> RenderedAudio:
        self._ensure_supported()
        text = request.text.strip()
        if not text:
            raise ValueError("TTS text cannot be empty.")

        if request.output_path is None:
            descriptor, raw_path = tempfile.mkstemp(prefix="myagent-tts-", suffix=".aiff")
            os.close(descriptor)
            Path(raw_path).unlink(missing_ok=True)
            output_path = Path(raw_path)
            cleanup_after_use = True
        else:
            output_path = request.output_path
            output_path.parent.mkdir(parents=True, exist_ok=True)
            cleanup_after_use = False

        command = ["say"]
        if request.voice:
            command.extend(["-v", request.voice])
        if request.rate is not None:
            command.extend(["-r", str(request.rate)])
        command.extend(["-o", str(output_path), text])
        process: subprocess.Popen[bytes] | None = None
        logger.info("tts_render_started path=%s monotonic=%.6f", output_path, time.monotonic())
        try:
            with self._lock:
                self.stop()
                process = subprocess.Popen(command)
                cancel_event = threading.Event()
                self._process = process
                self._cancel_event = cancel_event
            return_code = process.wait()
            if return_code != 0 and not cancel_event.is_set():
                raise subprocess.CalledProcessError(return_code, command)
        except BaseException:
            if cleanup_after_use:
                output_path.unlink(missing_ok=True)
            raise
        finally:
            with self._lock:
                if process is not None and self._process is process:
                    self._process = None
                    self._cancel_event = None
            logger.info("tts_render_finished path=%s monotonic=%.6f", output_path, time.monotonic())
        return RenderedAudio(output_path, cleanup_after_use=cleanup_after_use)

    def stop(self) -> bool:
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

    @staticmethod
    def _ensure_supported() -> None:
        if platform.system() != "Darwin":
            raise RuntimeError("MacOSSayAudioRenderer only works on macOS.")


class MacOSAudioPlayer:
    """Play pre-rendered audio with a stoppable macOS `afplay` process."""

    def __init__(self) -> None:
        self._process: subprocess.Popen[bytes] | None = None
        self._lock = threading.RLock()

    def play(self, audio: RenderedAudio) -> None:
        if platform.system() != "Darwin":
            raise RuntimeError("MacOSAudioPlayer only works on macOS.")
        with self._lock:
            self.stop()
            process = subprocess.Popen(["afplay", str(audio.path)])
            self._process = process
        logger.info("tts_play_started path=%s monotonic=%.6f", audio.path, time.monotonic())
        try:
            return_code = process.wait()
            if return_code != 0:
                raise subprocess.CalledProcessError(return_code, ["afplay", str(audio.path)])
        finally:
            logger.info("tts_play_finished path=%s monotonic=%.6f", audio.path, time.monotonic())
            with self._lock:
                if self._process is process:
                    self._process = None

    def stop(self) -> bool:
        with self._lock:
            process = self._process
            if process is None or process.poll() is not None:
                self._process = None
                return False
            process.terminate()
            self._process = None
            return True


class MacOSSayTTS:
    """Text-to-speech provider backed by macOS `say`."""

    def __init__(self) -> None:
        self._process: subprocess.Popen[bytes] | None = None
        self._cancel_event: threading.Event | None = None
        self._lock = threading.RLock()
        self._renderer = MacOSSayAudioRenderer()
        self._player = MacOSAudioPlayer()

    def render(self, request: TTSRequest) -> RenderedAudio:
        return self._renderer.render(request)

    def play(self, audio: RenderedAudio) -> None:
        self._player.play(audio)

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
        stopped = self._player.stop() or self._renderer.stop()
        with self._lock:
            process = self._process
            if process is None or process.poll() is not None:
                self._process = None
                self._cancel_event = None
                return stopped
            if self._cancel_event is not None:
                self._cancel_event.set()
            process.terminate()
            self._process = None
            self._cancel_event = None
            return True
