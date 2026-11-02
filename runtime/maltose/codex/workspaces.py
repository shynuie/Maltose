"""Isolated Git workspaces with a private working-copy baseline.

No user edits are committed, staged, reset, or copied back into the source.
The controller must explicitly authorize an exact repository before constructing
this service; this is not an unrestricted model-facing filesystem tool.
"""
from __future__ import annotations

import difflib
import hashlib
import json
import os
from pathlib import Path, PurePosixPath
import stat
import subprocess
import uuid


class CodexWorkspaceError(RuntimeError):
    pass


class CodexWorkspaceManager:
    schema_version = 1
    maximum_file_bytes = 128 * 1024 * 1024
    maximum_total_bytes = 1024 * 1024 * 1024

    def __init__(self, storage_root: Path, *, authorized_repositories: tuple[Path, ...]):
        self.storage_root = Path(storage_root).resolve()
        self.authorized = frozenset(Path(path).resolve(strict=True) for path in authorized_repositories)

    @staticmethod
    def _task_id(value: str) -> str:
        try: canonical = str(uuid.UUID(value))
        except (ValueError, TypeError, AttributeError) as error: raise CodexWorkspaceError('Invalid task ID') from error
        # Foundation emits uppercase UUIDs; Python emits lowercase. They identify one task.
        if not isinstance(value, str) or canonical != value.lower():
            raise CodexWorkspaceError('Task ID must use hyphenated UUID form')
        return canonical

    @staticmethod
    def _git(repository: Path, *arguments: str) -> bytes:
        environment = {key: value for key, value in os.environ.items() if not key.startswith('GIT_')}
        environment.update(GIT_CONFIG_NOSYSTEM='1', GIT_OPTIONAL_LOCKS='0')
        result = subprocess.run(
            ['/usr/bin/git', '-c', 'core.hooksPath=/dev/null', '-c', 'core.fsmonitor=false',
             '-c', 'submodule.recurse=false', '-C', str(repository), *arguments],
            stdout=subprocess.PIPE, stderr=subprocess.PIPE, env=environment, timeout=60, check=False)
        if result.returncode:
            # Git stderr may include private paths or source text. Keep it out of Agent output.
            raise CodexWorkspaceError(f'Git {arguments[0]} failed with status {result.returncode}')
        return result.stdout

    @staticmethod
    def _relative(raw: bytes) -> str:
        try: value = raw.decode('utf-8', errors='strict')
        except UnicodeDecodeError as error:
            raise CodexWorkspaceError('Non-UTF-8 source paths are not supported') from error
        path = PurePosixPath(value)
        if not value or path.is_absolute() or any(part in ('.git', '..') for part in path.parts) or '\x00' in value:
            raise CodexWorkspaceError('Invalid source path')
        return value

    def _paths(self, repository: Path) -> list[str]:
        cached = self._git(repository, 'ls-files', '-z', '--cached', '--others', '--exclude-standard')
        head = self._git(repository, 'ls-tree', '-rz', 'HEAD')
        paths = {self._relative(raw) for raw in cached.split(b'\x00') if raw}
        for record in head.split(b'\x00'):
            if not record: continue
            metadata, raw_path = record.split(b'\t', 1)
            if metadata.startswith(b'160000 '):
                raise CodexWorkspaceError('Submodule workspaces need explicit provisioning before delegation')
            paths.add(self._relative(raw_path))
        if len(paths) > 100_000: raise CodexWorkspaceError('Too many source paths')
        return sorted(paths)

    def _read(self, repository: Path, relative: str) -> tuple[dict, bytes] | None:
        self._relative(os.fsencode(relative))
        path = repository / relative
        parent = path.parent
        # Never follow an ancestor symlink while reading or deleting a target path.
        while parent != repository:
            try: mode = parent.lstat().st_mode
            except FileNotFoundError: return None
            if not stat.S_ISDIR(mode): raise CodexWorkspaceError('Source path has a non-directory ancestor')
            parent = parent.parent
        try: info = path.lstat()
        except FileNotFoundError: return None
        if stat.S_ISLNK(info.st_mode):
            link = os.readlink(path)
            target = (path.parent / link).resolve()
            if Path(link).is_absolute() or not target.is_relative_to(repository) \
                or '.git' in target.relative_to(repository).parts:
                raise CodexWorkspaceError('Absolute or escaping source symlinks need explicit provisioning')
            data = os.fsencode(link); kind = 'symlink'; executable = False
        elif stat.S_ISREG(info.st_mode):
            fd = os.open(path, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK | os.O_CLOEXEC)
            with os.fdopen(fd, 'rb') as stream:
                actual = os.fstat(stream.fileno())
                if not stat.S_ISREG(actual.st_mode) or actual.st_size > self.maximum_file_bytes:
                    raise CodexWorkspaceError('Source file type or size is not supported')
                data = stream.read(self.maximum_file_bytes + 1)
            if len(data) > self.maximum_file_bytes: raise CodexWorkspaceError('Source file exceeds size limit')
            kind = 'file'; executable = bool(actual.st_mode & 0o111)
        else: raise CodexWorkspaceError('Nested repositories, devices and special source files are not supported')
        return {'kind': kind, 'sha256': hashlib.sha256(data).hexdigest(), 'executable': executable, 'bytes': len(data)}, data

    def _snapshot(self, repository: Path, destinations: tuple[Path, ...] = ()) -> dict:
        entries = {}; total = 0
        for relative in self._paths(repository):
            item = self._read(repository, relative)
            if item is None: continue
            entry, data = item; total += len(data)
            if total > self.maximum_total_bytes: raise CodexWorkspaceError('Source snapshot exceeds size limit')
            entries[relative] = entry
            for destination in destinations:
                target = destination / relative
                target.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
                if entry['kind'] == 'symlink': target.symlink_to(os.fsdecode(data))
                else:
                    fd = os.open(target, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o700 if entry['executable'] else 0o600)
                    with os.fdopen(fd, 'wb') as stream: stream.write(data)
        return entries

    @staticmethod
    def _save(path: Path, document: dict) -> None:
        temporary = path.with_name(f'.{path.name}-{uuid.uuid4().hex}.tmp')
        try:
            fd = os.open(temporary, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600)
            with os.fdopen(fd, 'w', encoding='utf-8') as stream:
                json.dump(document, stream, ensure_ascii=False, sort_keys=True)
                stream.flush(); os.fsync(stream.fileno())
            os.replace(temporary, path)
            fd = os.open(path.parent, os.O_RDONLY | os.O_DIRECTORY)
            try: os.fsync(fd)
            finally: os.close(fd)
        finally:
            temporary.unlink(missing_ok=True)

    def prepare(self, repository: Path, task_id: str) -> dict:
        repository = Path(repository).resolve(strict=True)
        if repository not in self.authorized:
            raise PermissionError('Repository has not been explicitly authorized for Codex')
        canonical_id = self._task_id(task_id)
        if self.storage_root.is_relative_to(repository) or repository.is_relative_to(self.storage_root):
            raise CodexWorkspaceError('Workspace storage must be separate from the source repository')
        top = Path(os.fsdecode(self._git(repository, 'rev-parse', '--show-toplevel')).strip()).resolve()
        if top != repository: raise CodexWorkspaceError('Authorize the exact Git repository root')
        head = self._git(repository, 'rev-parse', 'HEAD').decode().strip()
        index_before = self._git(repository, 'diff', '--cached', '--binary', '--no-ext-diff', '--no-textconv')
        status_before = self._git(repository, 'status', '--porcelain=v1', '-z', '--untracked-files=all')
        before = self._snapshot(repository)
        self.storage_root.mkdir(parents=True, exist_ok=True, mode=0o700)
        job = self.storage_root / canonical_id
        job.mkdir(mode=0o700)  # Refuse reuse/overwrite of any existing attempt.
        baseline, workspace = job / 'baseline', job / 'worktree'
        receipt_path = job / 'receipt.json'
        receipt = dict(schemaVersion=self.schema_version, taskID=canonical_id, repository=str(repository),
                       worktree=str(workspace), baseline=str(baseline), head=head, phase='preparing')
        self._save(receipt_path, receipt)
        try:
            baseline.mkdir(mode=0o700)
            # No checkout means no smudge/filter processes, LFS downloads, or post-checkout hooks.
            self._git(repository, 'worktree', 'add', '--no-checkout', '--detach', '--', str(workspace), head)
            workspace.chmod(0o700)
            self._git(workspace, 'reset', '--mixed', 'HEAD')  # New worktree index only; source index stays intact.
            copied = self._snapshot(repository, (baseline, workspace))
            after = self._snapshot(repository)
            if before != copied or copied != after or head != self._git(repository, 'rev-parse', 'HEAD').decode().strip() \
                or status_before != self._git(repository, 'status', '--porcelain=v1', '-z', '--untracked-files=all') \
                or index_before != self._git(repository, 'diff', '--cached', '--binary', '--no-ext-diff', '--no-textconv'):
                raise CodexWorkspaceError('Source changed during preparation; preserve this attempt and prepare a fresh task')
            receipt.update(phase='ready', entries=copied,
                           sourceIndexSHA256=hashlib.sha256(index_before).hexdigest(),
                           sourceStatusSHA256=hashlib.sha256(status_before).hexdigest())
            self._save(receipt_path, receipt)
            return receipt
        except BaseException:
            receipt['phase'] = 'incomplete'
            self._save(receipt_path, receipt)
            # Keep the owned attempt/registration for inspection; never delete unexpected edits.
            raise

    def inspect(self, task_id: str) -> dict:
        task_id = self._task_id(task_id)
        job = self.storage_root / task_id
        if job.is_symlink() or not job.is_dir(): raise CodexWorkspaceError('Invalid workspace directory')
        receipt_path = job / 'receipt.json'
        fd = os.open(receipt_path, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK)
        with os.fdopen(fd, 'rb') as stream:
            info = os.fstat(stream.fileno())
            if not stat.S_ISREG(info.st_mode) or info.st_uid != os.getuid() or info.st_mode & 0o077 \
                or info.st_nlink != 1 or info.st_size > 64 * 1024 * 1024:
                raise CodexWorkspaceError('Invalid workspace receipt ownership, type or size')
            receipt = json.loads(stream.read(64 * 1024 * 1024 + 1))
        if receipt.get('schemaVersion') != self.schema_version or receipt.get('phase') not in ('ready', 'preparing', 'incomplete') \
            or receipt.get('taskID') != task_id or receipt.get('repository') not in {str(path) for path in self.authorized} \
            or receipt.get('worktree') != str(job / 'worktree') or receipt.get('baseline') != str(job / 'baseline'):
            raise CodexWorkspaceError('Workspace receipt does not match the authorized task')
        return receipt

    def changes(self, task_id: str, *, max_diff_chars: int = 100_000) -> dict:
        if not 1 <= max_diff_chars <= 1_000_000: raise CodexWorkspaceError('Invalid diff size limit')
        task_id = self._task_id(task_id)
        receipt = self.inspect(task_id)
        if receipt['phase'] != 'ready': raise CodexWorkspaceError('Workspace preparation is incomplete')
        workspace, baseline = Path(receipt['worktree']), Path(receipt['baseline'])
        if workspace.is_symlink() or baseline.is_symlink() or not workspace.is_dir() or not baseline.is_dir():
            raise CodexWorkspaceError('Workspace or baseline directory identity changed')
        if self._git(workspace, 'rev-parse', '--show-toplevel').strip() != os.fsencode(workspace):
            raise CodexWorkspaceError('Workspace Git identity changed')
        current = self._snapshot(workspace)
        changes = []; remaining = max_diff_chars
        for relative in sorted(set(receipt['entries']) | set(current)):
            previous, new = receipt['entries'].get(relative), current.get(relative)
            original = self._read(baseline, relative)
            if (original[0] if original else None) != previous: raise CodexWorkspaceError('Private baseline was altered')
            if previous == new: continue
            actual = self._read(workspace, relative)
            if (actual[0] if actual else None) != new: raise CodexWorkspaceError('Workspace changed while collecting results')
            entry = dict(path=relative, before=previous, after=new)
            if sum(part[0]['bytes'] for part in (original, actual) if part) > 1024 * 1024:
                entry['diffUnavailable'] = 'file_too_large'
                changes.append(entry); continue
            try:
                old_text = original[1].decode('utf-8') if original else ''
                new_text = actual[1].decode('utf-8') if actual else ''
                if '\x00' in old_text + new_text: raise UnicodeDecodeError('utf-8', b'\0', 0, 1, 'binary content')
                diff = ''.join(difflib.unified_diff(old_text.splitlines(keepends=True), new_text.splitlines(keepends=True),
                                                 fromfile='baseline/' + relative, tofile='worktree/' + relative))
                entry.update(diff=diff[:remaining], truncated=len(diff) > remaining)
                remaining = max(0, remaining - len(diff))
            except UnicodeDecodeError: entry['binary'] = True
            changes.append(entry)
        # A concurrent edit invalidates this report rather than attributing a mixed snapshot.
        if current != self._snapshot(workspace): raise CodexWorkspaceError('Workspace changed while collecting results')
        return dict(taskID=task_id, head=receipt['head'], changes=changes, sourceState=self._source_state(receipt))

    def _source_state(self, receipt):
        """Read-only provenance; source edits are reported, never reset/staged."""
        source = Path(receipt['repository'])
        try:
            if source.is_symlink() or source.resolve(strict=True) != source: raise CodexWorkspaceError('Source identity changed')
            head = self._git(source, 'rev-parse', 'HEAD').decode().strip()
            files = self._snapshot(source)
            index = self._git(source, 'diff', '--cached', '--binary', '--no-ext-diff', '--no-textconv')
            status = self._git(source, 'status', '--porcelain=v1', '-z', '--untracked-files=all')
            stable = head == self._git(source, 'rev-parse', 'HEAD').decode().strip() and files == self._snapshot(source) \
                and index == self._git(source, 'diff', '--cached', '--binary', '--no-ext-diff', '--no-textconv') \
                and status == self._git(source, 'status', '--porcelain=v1', '-z', '--untracked-files=all')
            return dict(checked=stable, headMatchesBaseline=head == receipt['head'] if stable else None,
                filesMatchBaseline=files == receipt['entries'] if stable else None,
                indexMatchesBaseline=hashlib.sha256(index).hexdigest() == receipt['sourceIndexSHA256'] if stable and 'sourceIndexSHA256' in receipt else None,
                statusMatchesBaseline=hashlib.sha256(status).hexdigest() == receipt['sourceStatusSHA256'] if stable and 'sourceStatusSHA256' in receipt else None)
        except (OSError, CodexWorkspaceError):
            return dict(checked=False, note='Original source state could not be verified; it was not modified by this inspection.')
