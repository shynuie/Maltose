"""Durable Docker ownership, used only by the native lifetime guardian.

The guardian creates stopped containers and records their exact identity before
allowing the main runtime to start them. Recovery only removes owned containers;
it never recreates or starts an interrupted execution.
"""
from __future__ import annotations
import json
import math
import os
from pathlib import Path
import re
import stat
import subprocess
import sys
import uuid

from maltose.runtime.processes import Identity


class ResourceCleanupError(RuntimeError):
    pass


class DockerResources:
    def __init__(self, directory: Path, binary: str | None, scope: str):
        self.directory = directory
        directory.mkdir(parents=True, exist_ok=True, mode=0o700)
        info = directory.lstat()
        if not stat.S_ISDIR(info.st_mode) or info.st_uid != os.getuid() or info.st_mode & 0o077:
            raise ResourceCleanupError('Native execution receipts require a private real directory')
        self.binary, self.scope = binary, self.execution(scope)

    @staticmethod
    def execution(value):
        if not isinstance(value, str) or not re.fullmatch('[a-f0-9]{32}', value):
            raise ResourceCleanupError('Invalid execution identity')
        return value

    def read(self, execution):
        path = self.directory / (self.execution(execution) + '.json')
        descriptor = os.open(path, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK)
        with os.fdopen(descriptor, 'rb') as stream:
            info = os.fstat(stream.fileno())
            if not stat.S_ISREG(info.st_mode) or info.st_size > 8192 or info.st_uid != os.getuid() or info.st_mode & 0o077:
                raise ResourceCleanupError('Invalid private execution receipt')
            data = stream.read(8193)
            if len(data) > 8192: raise ResourceCleanupError('Execution receipt exceeds size limit')
            record = json.loads(data)
        if record.get('schemaVersion') != 1 or record.get('executionID') != execution:
            raise ResourceCleanupError('Execution receipt does not match its identity')
        self.execution(record.get('scope'))
        if record.get('phase') not in ('creating', 'created', 'cleaned', 'uncertain'):
            raise ResourceCleanupError('Unknown execution receipt phase')
        if record.get('containerID') is not None and not re.fullmatch('[a-f0-9]{64}', record['containerID']):
            raise ResourceCleanupError('Invalid recorded container identity')
        if not isinstance(record.get('creationFinished'), bool):
            raise ResourceCleanupError('Invalid creation completion state')
        if record['phase'] in ('created', 'cleaned') and not record['creationFinished']:
            raise ResourceCleanupError('Execution completion state is inconsistent')
        if record['phase'] == 'created' and record['containerID'] is None:
            raise ResourceCleanupError('Created execution has no durable container ID')
        if 'admissionVersion' in record and (record['admissionVersion'] != 1 or type(record.get('launchPermitted')) is not bool):
            raise ResourceCleanupError('Invalid creator admission state')
        creator = record.get('creator')
        if creator is not None and (not isinstance(creator, dict)
            or type(creator.get('pid')) is not int or creator['pid'] <= 1
            or type(creator.get('created')) not in (int, float)
            or not math.isfinite(creator['created']) or creator['created'] <= 0):
            raise ResourceCleanupError('Invalid creator process identity')
        return record

    def save(self, record):
        path = self.directory / (self.execution(record['executionID']) + '.json')
        temporary = self.directory / ('.' + uuid.uuid4().hex + '.tmp')
        try:
            fd = os.open(temporary, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600)
            with os.fdopen(fd, 'w') as stream:
                json.dump(record, stream); stream.flush(); os.fsync(stream.fileno())
            os.replace(temporary, path)
            fd = os.open(self.directory, os.O_RDONLY)
            try: os.fsync(fd)
            finally: os.close(fd)
        finally:
            temporary.unlink(missing_ok=True)

    def backend(self):
        from maltose.execution.docker_backend import DockerSandboxBackend
        if not self.binary or not Path(self.binary).is_absolute():
            raise ResourceCleanupError('Docker is unavailable; pending execution cleanup cannot be confirmed')
        backend = DockerSandboxBackend(image='unused-for-cleanup', docker_binary=self.binary)
        backend._resolved_binary = self.binary
        return backend

    def lookup(self, execution):
        backend = self.backend()
        return backend._owned_container_identity('maltose-exec-' + execution, execution)

    def create(self, execution, command):
        self.execution(execution)
        backend = self.backend()
        name = 'maltose-exec-' + execution
        prefix = [self.binary, 'run', '--name', name, '--label', 'dev.maltose.execution-id=' + execution]
        if not isinstance(command, list) or command[:6] != prefix or not all(isinstance(arg, str) and '\0' not in arg for arg in command):
            raise ResourceCleanupError('Execution request does not match its scoped Docker command')
        path = self.directory / (execution + '.json')
        if path.exists() or path.is_symlink():
            raise ResourceCleanupError('Execution identity was already registered; it cannot be replayed')
        record = dict(schemaVersion=1, scope=self.scope, executionID=execution, phase='creating',
                      containerID=None, creationFinished=False, creator=None, admissionVersion=1, launchPermitted=False)
        self.save(record)  # Durable before the first daemon mutation.
        process = None
        try:
            process = subprocess.Popen([sys.executable, '-m', 'maltose.runtime.worker', '--exec-after-ready',
                self.binary, 'create', *command[2:]], stdin=subprocess.PIPE,
                stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
            identity = Identity.read(process.pid)
            record['creator'] = dict(pid=identity.pid, created=identity.created)
            self.save(record)
            record['launchPermitted'] = True
            self.save(record)
            output, _ = process.communicate(input='1', timeout=10)
            record['creationFinished'] = True
            self.save(record)
            container = output.strip()
            if process.returncode != 0 or not re.fullmatch('[a-f0-9]{64}', container):
                raise ResourceCleanupError('Docker create did not return a confirmed container identity')
            # Cross-check daemon metadata, not just stdout, before authorizing start.
            if self.lookup(execution) != container:
                raise ResourceCleanupError('Created container does not match its execution name and label')
            record.update(phase='created', containerID=container)
            self.save(record)  # Start is permitted only after this durable identity.
            return container
        except BaseException:
            if process is not None and process.poll() is None:
                process.kill(); process.communicate(timeout=3)
            elif process is None:
                record['creationFinished'] = True  # The create request was never launched.
                self.save(record)
            try: self.cleanup(execution)
            except Exception: pass  # Preserve the pending receipt; never claim cleanup.
            raise

    def cleanup(self, execution, *, current_scope=False):
        record = self.read(execution)
        if current_scope and record['scope'] != self.scope:
            raise ResourceCleanupError('Execution belongs to another runtime scope')
        if record['phase'] == 'cleaned': return
        creator = record.get('creator')
        if not record.get('creationFinished') and creator:
            identity = Identity(creator['pid'], creator['created'])
            process = identity.process()
            if process is not None:
                arguments = process.cmdline()
                expected = [self.binary, 'create', '--name', 'maltose-exec-' + execution,
                            '--label', 'dev.maltose.execution-id=' + execution]
                wrapper=[sys.executable, '-m', 'maltose.runtime.worker', '--exec-after-ready', *expected]
                matches=(arguments[:6]==expected or arguments[:len(wrapper)]==wrapper
                    or arguments[1:7]==expected)  # Trusted executable may itself be a script.
                if not matches:
                    raise ResourceCleanupError('Recorded creator identity no longer matches its Docker operation')
                process.kill()
                try: process.wait(timeout=3)
                except Exception as error: raise ResourceCleanupError('Docker creator has not stopped') from error
        if record.get('admissionVersion')==1 and not record['launchPermitted']:
            record.update(phase='cleaned', creationFinished=True)
            self.save(record)
            return
        identity = self.lookup(execution)
        if identity is None and not record.get('creationFinished'):
            record['phase'] = 'uncertain'; self.save(record)
            raise ResourceCleanupError('Interrupted Docker creation is unconfirmed; no execution was replayed')
        if identity is not None and record['containerID'] is None:
            record.update(containerID=identity, phase='created', creationFinished=True)
            self.save(record)
        self.backend()._remove_owned_container('maltose-exec-' + execution, execution,
            expected_identity=record.get('containerID'))
        record.update(phase='cleaned', creationFinished=True)
        self.save(record)

    def has_pending(self):
        try: return any(self.read(self.execution(path.stem))['phase'] != 'cleaned' for path in self.directory.glob('*.json'))
        except Exception: return True

    def recover(self):
        for path in sorted(self.directory.glob('*.json')):
            self.cleanup(self.execution(path.stem))
