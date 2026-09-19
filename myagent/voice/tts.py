from __future__ import annotations

import platform
import subprocess
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
        subprocess.run(command, check=True)
