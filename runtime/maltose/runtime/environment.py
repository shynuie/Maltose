"""Load private service credentials as data, without sourcing a shell script."""
from __future__ import annotations
import os
from pathlib import Path
import re
import shlex
import stat
from collections.abc import MutableMapping

SERVICE_CREDENTIALS = frozenset({'OPENAI_API_KEY', 'TASKBRAIN_TOKEN', 'BRAVE_SEARCH_API_KEY', 'OPENCLAW_GATEWAY_TOKEN'})


def parse_service_credentials(contents: str) -> dict[str, str]:
    credentials = {}
    for line in contents.splitlines():
        line = line.strip()
        if not line or line.startswith('#'): continue
        if line.startswith('export '): line = line[7:].lstrip()
        name, separator, raw = line.partition('=')
        name, raw = name.strip(), raw.strip()
        if not separator or name not in SERVICE_CREDENTIALS or name in credentials:
            raise ValueError('Private environment file contains an unsupported or duplicate credential setting')
        if raw.startswith(('"', "'")):
            try: tokens = shlex.split(raw, comments=True, posix=True)
            except ValueError: raise ValueError('Private credential quoting is invalid') from None
            if len(tokens) != 1: raise ValueError('A private credential must have one quoted value')
            value = tokens[0]
        else:
            # Match plain shell assignments' inline # behavior, preserving token hashes.
            value = re.split(r'\s+#', raw, maxsplit=1)[0].strip()
            if any(character.isspace() for character in value):
                raise ValueError('Private credential values containing spaces must be quoted')
        if not value: raise ValueError('A private credential value is empty')
        credentials[name] = value
    return credentials


def load_private_environment(path: Path, *, environ: MutableMapping[str, str] | None = None) -> None:
    try: descriptor = os.open(path, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK)
    except FileNotFoundError: return
    with os.fdopen(descriptor, 'rb') as stream:
        attributes = os.fstat(stream.fileno())
        if not stat.S_ISREG(attributes.st_mode) or attributes.st_uid != os.getuid() or attributes.st_mode & 0o077:
            raise PermissionError('Private runtime environment must be an owner-only regular file (mode 600)')
        if attributes.st_size > 65536: raise ValueError('Private runtime environment exceeds the size limit')
        contents = stream.read(65537)
        if len(contents) > 65536: raise ValueError('Private runtime environment exceeds the size limit')
        try: credentials = parse_service_credentials(contents.decode('utf-8'))
        except UnicodeError: raise ValueError('Private runtime environment must use UTF-8') from None
    target = os.environ if environ is None else environ
    for key, value in credentials.items(): target.setdefault(key, value)
