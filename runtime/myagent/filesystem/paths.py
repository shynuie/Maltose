"""Safe root-relative path resolution for filesystem capabilities."""

from __future__ import annotations

from dataclasses import dataclass
from fnmatch import fnmatch
from pathlib import Path
from typing import Mapping


@dataclass(frozen=True)
class FilesystemRoot:
    """A named filesystem root exposed to a capability service."""

    name: str
    path: Path
    read: bool = True
    write: bool = False
    delete: bool = False


@dataclass(frozen=True)
class ResolvedPath:
    """A validated path and its safe, root-relative representation."""

    root: FilesystemRoot
    path: Path
    relative_path: str


class PathResolver:
    """Resolve only safe paths below explicitly configured roots.

    This class intentionally performs no file mutation. Callers should use the
    returned ``ResolvedPath`` as the only path value passed to filesystem I/O.
    """

    def __init__(
        self,
        roots: Mapping[str, str | Path | FilesystemRoot],
        *,
        protected_paths: tuple[str, ...] = (),
    ) -> None:
        if not roots:
            raise ValueError("At least one filesystem root is required.")
        self._roots: dict[str, FilesystemRoot] = {}
        for name, value in roots.items():
            if isinstance(value, FilesystemRoot):
                if value.name != name:
                    raise ValueError("Filesystem root mapping key must match root name.")
                root = value
            else:
                root = FilesystemRoot(name=name, path=Path(value))
            self._roots[name] = FilesystemRoot(
                name=name,
                path=root.path.expanduser().resolve(),
                read=root.read,
                write=root.write,
                delete=root.delete,
            )
        if any(not name for name in self._roots):
            raise ValueError("Filesystem root names cannot be empty.")
        self._protected_paths = tuple(protected_paths)

    def resolve(
        self,
        root_name: str,
        relative_path: str | Path,
        *,
        must_exist: bool = False,
    ) -> ResolvedPath:
        root = self._get_root(root_name)
        relative = self._validate_relative_path(relative_path)
        relative_text = relative.as_posix()
        if self._is_protected(relative_text):
            raise PermissionError(f"Protected filesystem path: {relative_text}")

        candidate = (root.path / relative).resolve(strict=False)
        self._ensure_inside_root(root, candidate)
        self._reject_symlink_components(root.path, relative)

        if must_exist and not candidate.exists():
            raise FileNotFoundError(candidate)
        if candidate.exists() and candidate.is_file() and candidate.stat().st_nlink > 1:
            raise PermissionError(f"Hard-linked file is not allowed: {relative_text}")

        return ResolvedPath(root=root, path=candidate, relative_path=relative_text)

    def _get_root(self, root_name: str) -> FilesystemRoot:
        try:
            return self._roots[root_name]
        except KeyError as exc:
            raise PermissionError(f"Unknown filesystem root: {root_name}") from exc

    def root(self, root_name: str) -> FilesystemRoot:
        """Return a configured root without resolving a user path."""
        return self._get_root(root_name)

    def is_within(self, resolved: ResolvedPath, root_name: str, relative_path: str | Path = ".") -> bool:
        """Return whether a resolved path is below another configured path."""
        boundary = self.resolve(root_name, relative_path).path
        try:
            resolved.path.relative_to(boundary)
        except ValueError:
            return False
        return True

    @staticmethod
    def _validate_relative_path(value: str | Path) -> Path:
        if not isinstance(value, (str, Path)):
            raise TypeError("Filesystem path must be a string or Path.")
        raw = str(value)
        if not raw or "\x00" in raw:
            raise ValueError("Filesystem path must be non-empty and contain no NUL bytes.")
        relative = Path(raw)
        if relative.is_absolute():
            raise PermissionError("Filesystem path must be relative to its configured root.")
        if any(part == ".." for part in relative.parts):
            raise PermissionError("Filesystem path cannot contain '..'.")
        return relative

    @staticmethod
    def _ensure_inside_root(root: FilesystemRoot, candidate: Path) -> None:
        try:
            candidate.relative_to(root.path)
        except ValueError as exc:
            raise PermissionError(
                f"Filesystem path escapes root '{root.name}': {candidate}"
            ) from exc

    @staticmethod
    def _reject_symlink_components(root: Path, relative: Path) -> None:
        current = root
        for component in relative.parts:
            current /= component
            if current.is_symlink():
                raise PermissionError(f"Symlink path component is not allowed: {current}")

    def _is_protected(self, relative_path: str) -> bool:
        return any(
            fnmatch(relative_path, pattern) or fnmatch(Path(relative_path).name, pattern)
            for pattern in self._protected_paths
        )
