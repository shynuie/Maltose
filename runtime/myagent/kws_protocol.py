"""Small framed protocol shared by the main process and KWS workers."""

from __future__ import annotations

import json
import struct
from typing import BinaryIO, Any

HEADER = struct.Struct(">BI")
PCM = 1
RESET = 2
SHUTDOWN = 3
HEALTH = 4
RESPONSE = 16
READY = 17
ERROR = 18


def write_message(stream: BinaryIO, kind: int, payload: bytes = b"") -> None:
    stream.write(HEADER.pack(kind, len(payload)))
    stream.write(payload)
    stream.flush()


def read_message(stream: BinaryIO) -> tuple[int, bytes] | None:
    header = stream.read(HEADER.size)
    if not header:
        return None
    if len(header) != HEADER.size:
        raise EOFError("incomplete KWS protocol header")
    kind, length = HEADER.unpack(header)
    payload = stream.read(length)
    if len(payload) != length:
        raise EOFError("incomplete KWS protocol payload")
    return kind, payload


def json_bytes(value: Any) -> bytes:
    return json.dumps(value, ensure_ascii=False, separators=(",", ":")).encode("utf-8")


def parse_json(payload: bytes) -> Any:
    return json.loads(payload.decode("utf-8"))
