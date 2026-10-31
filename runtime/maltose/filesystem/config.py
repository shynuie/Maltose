"""Declarative filesystem sandbox configuration."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any

from maltose.filesystem.paths import FilesystemRoot, PathResolver
from maltose.filesystem.policy import PolicyEngine, WorkingRoot


@dataclass(frozen=True)
class FilesystemConfig:
    roots: tuple[FilesystemRoot, ...]
    working_root: WorkingRoot
    protected_paths: tuple[str, ...] = (".env", ".git/*", "**/credentials*", "**/*secret*")
    max_read_bytes: int = 1_048_576
    max_search_results: int = 100

    @classmethod
    def from_mapping(cls, mapping: dict[str, Any]) -> "FilesystemConfig":
        document = mapping.get("filesystem", mapping)
        if not isinstance(document, dict):
            raise ValueError("filesystem config must be an object.")
        raw_roots = document.get("roots")
        if not isinstance(raw_roots, dict) or not raw_roots:
            raise ValueError("filesystem.roots must be a non-empty object.")
        roots: list[FilesystemRoot] = []
        for name, raw in raw_roots.items():
            if not isinstance(name, str) or not name.strip() or not isinstance(raw, dict):
                raise ValueError("Each filesystem root needs a name and object config.")
            path = raw.get("path")
            if not isinstance(path, (str, Path)):
                raise ValueError(f"Filesystem root needs a path: {name}")
            roots.append(FilesystemRoot(
                name=name, path=Path(path), read=bool(raw.get("read", False)),
                write=bool(raw.get("write", False)), delete=bool(raw.get("delete", False)),
            ))
        raw_working = document.get("working_root")
        if isinstance(raw_working, str):
            working = WorkingRoot(raw_working)
        elif isinstance(raw_working, dict) and isinstance(raw_working.get("root"), str):
            working = WorkingRoot(raw_working["root"], str(raw_working.get("path", ".")))
        else:
            raise ValueError("filesystem.working_root must name a root.")
        root_by_name = {root.name: root for root in roots}
        selected = root_by_name.get(working.root)
        if selected is None:
            raise ValueError("working_root must reference a configured root.")
        if not selected.write or not selected.delete:
            raise ValueError("working_root must allow write and delete operations.")
        protected = document.get("protected_paths", cls.protected_paths)
        if not isinstance(protected, list) or not all(isinstance(item, str) for item in protected):
            raise ValueError("protected_paths must be a list of strings.")
        max_read = int(document.get("max_read_bytes", cls.max_read_bytes))
        max_search = int(document.get("max_search_results", cls.max_search_results))
        if max_read <= 0 or max_search <= 0:
            raise ValueError("Filesystem limits must be positive.")
        return cls(tuple(roots), working, tuple(protected), max_read, max_search)

    def resolver(self) -> PathResolver:
        return PathResolver({root.name: root for root in self.roots}, protected_paths=self.protected_paths)

    def policy(self) -> PolicyEngine:
        return PolicyEngine(
            self.resolver(), working_root=self.working_root,
            max_read_bytes=self.max_read_bytes, max_search_results=self.max_search_results,
        )
