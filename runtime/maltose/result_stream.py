"""Incremental *draft* text from the final-answer envelope.

Only a top-level JSON string named full_text is exposed. The completed envelope
still needs AnswerResult validation; this parser grants no publication rights.
"""
from __future__ import annotations

from dataclasses import dataclass
import json


@dataclass(frozen=True)
class ResultTextDelta:
    content: str = ''
    reset: bool = False


class ResultTextDecoder:
    maximum_bytes = 2 * 1024 * 1024

    def __init__(self):
        self._buffer = ''
        self._position = 0
        self._bytes = 0
        self._state = 'root'
        self._key = None
        self._seen = set()
        self._decoder = json.JSONDecoder()
        self.has_text = False

    def feed(self, chunk: str) -> str:
        if self._state == 'invalid': return ''
        self._bytes += len(chunk.encode('utf-8'))
        if self._bytes > self.maximum_bytes:
            self._state = 'invalid'
            self._buffer = ''
            return ''
        self._buffer += chunk
        parts = []
        while self._position < len(self._buffer):
            if self._state == 'body':
                position = self._position
                character = self._buffer[position]
                if character == '"':
                    self._position += 1
                    self._state = 'after'
                    continue
                if ord(character) < 32:
                    self._state = 'invalid'
                    break
                if character != '\\':
                    # Consume ordinary characters together, retaining newlines
                    # only when JSON encoded them as escapes.
                    end = position + 1
                    while end < len(self._buffer) and self._buffer[end] not in '\\"' and ord(self._buffer[end]) >= 32:
                        end += 1
                    parts.append(self._buffer[position:end])
                    self._position = end
                    continue
                if position + 1 >= len(self._buffer): break
                escape = self._buffer[position + 1]
                escapes = {'"': '"', '\\': '\\', '/': '/', 'b': '\b', 'f': '\f', 'n': '\n', 'r': '\r', 't': '\t'}
                if escape in escapes:
                    parts.append(escapes[escape])
                    self._position += 2
                    continue
                if escape != 'u':
                    self._state = 'invalid'
                    break
                if position + 6 > len(self._buffer): break
                try:
                    value = int(self._buffer[position + 2:position + 6], 16)
                    end = position + 6
                    if 0xD800 <= value <= 0xDBFF:
                        if position + 12 > len(self._buffer): break
                        if self._buffer[end:end + 2] != '\\u': raise ValueError('Missing low surrogate')
                        low = int(self._buffer[end + 2:end + 6], 16)
                        if not 0xDC00 <= low <= 0xDFFF: raise ValueError('Invalid low surrogate')
                        value = 0x10000 + ((value - 0xD800) << 10) + low - 0xDC00
                        end += 6
                    elif 0xDC00 <= value <= 0xDFFF:
                        raise ValueError('Unpaired low surrogate')
                    parts.append(chr(value))
                    self._position = end
                except ValueError:
                    self._state = 'invalid'
                    break
                continue

            character = self._buffer[self._position]
            if character in ' \t\r\n':
                self._position += 1
                continue
            if self._state == 'root':
                self._state = 'key' if character == '{' else 'invalid'
                self._position += 1
            elif self._state == 'key':
                if character != '"':
                    self._state = 'invalid'
                    break
                try: key, end = self._decoder.raw_decode(self._buffer, self._position)
                except ValueError: break  # A key may span transport chunks.
                if key in self._seen:
                    self._state = 'invalid'
                    break
                self._key = key
                self._seen.add(key)
                self._position = end
                self._state = 'colon'
            elif self._state == 'colon':
                self._state = 'value' if character == ':' else 'invalid'
                self._position += 1
            elif self._state == 'value':
                if self._key == 'full_text':
                    self._state = 'body' if character == '"' else 'invalid'
                    self._position += 1
                    continue
                try: _, end = self._decoder.raw_decode(self._buffer, self._position)
                except ValueError: break
                # Wait for a delimiter: e.g. 1 at a chunk boundary could be 10.
                separator = end
                while separator < len(self._buffer) and self._buffer[separator] in ' \t\r\n': separator += 1
                if separator == len(self._buffer): break
                if self._buffer[separator] not in ',}':
                    self._state = 'invalid'
                    break
                self._position = separator
                self._state = 'after'
            elif self._state == 'after':
                self._state = 'key' if character == ',' else 'done' if character == '}' else 'invalid'
                self._position += 1
            else:
                self._state = 'invalid'
                break
        text = ''.join(parts)
        self.has_text = self.has_text or bool(text)
        return text
