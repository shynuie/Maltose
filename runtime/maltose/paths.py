"""Product paths and explicit compatibility with pre-unification configuration."""
from __future__ import annotations

import os
from pathlib import Path
from typing import Mapping


def environment_value(name: str, default: str | None = None,
                      *, environ: Mapping[str, str] | None = None) -> str | None:
    values = os.environ if environ is None else environ
    return values.get(f"MALTOSE_{name}", values.get(f"MYAGENT_{name}", default))


def default_config_path(directory: Path | None = None,
                        *, environ: Mapping[str, str] | None = None) -> Path:
    """Select one config, never silently merge conflicting new and legacy values."""
    base = directory or Path.cwd()
    explicit = environment_value("CONFIG", environ=environ)
    if explicit is not None:
        path = Path(explicit).expanduser()
        return path if path.is_absolute() else base / path
    current = base / "maltose.toml"
    legacy = base / "myagent.toml"
    return current if current.exists() or not legacy.exists() else legacy


def application_support(*, environ: Mapping[str, str] | None = None) -> Path:
    override = environment_value("DATA_DIR", environ=environ)
    return Path(override).expanduser() if override else Path.home() / "Library/Application Support/Maltose"
