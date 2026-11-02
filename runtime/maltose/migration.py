"""Versioned, recoverable import of an existing local Agent installation.

Private manifests and backups belong under Application Support, never in Git.
The source installation remains intact. Config is published last, under the
same lease used by the native runtime, so an app cannot use a partial import.
"""
from __future__ import annotations
import argparse
import ctypes
import hashlib
import json
import math
import os
from pathlib import Path
import shutil
import sqlite3
import subprocess
import sys
import tomllib
import uuid

from maltose.runtime.environment import parse_service_credentials
from maltose.runtime.ownership import RuntimeLease

TREES = ('data', 'documents', 'models', 'recordings', 'tools/location_helper.app')
CONFIG_PATHS = {
    'agent': ('output_dir',), 'environment': ('location_helper',),
    'taskbrain': ('memory', 'memory_source', 'tasks', 'speaker_profiles', 'speaker_model_dir'),
    'knowledge': ('documents_root', 'metadata', 'vectors', 'queue'),
    'wake': ('config',),
}


def digest(path: Path) -> str:
    with path.open('rb') as stream:
        result = hashlib.file_digest(stream, 'sha256')
    return result.hexdigest()


def fingerprint(path: Path) -> dict:
    if path.is_symlink(): return {'link': os.readlink(path), 'content': digest(path) if path.is_file() else None}
    if path.is_file(): return {'sha256': digest(path)}
    if path.is_dir(): return {p.name: fingerprint(p) for p in sorted(path.iterdir())}
    raise ValueError('Migration contains a missing or unsupported filesystem object')


def atomic_json(path: Path, value: dict) -> None:
    temporary = path.with_name(path.name + '.new')
    with temporary.open('w', encoding='utf-8') as stream:
        json.dump(value, stream, ensure_ascii=False, indent=2)
        stream.flush(); os.fsync(stream.fileno())
    temporary.chmod(0o600)
    os.replace(temporary, path)


def copy_file(source: Path, target: Path) -> None:
    target.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    cloned = False
    if sys.platform == 'darwin':
        library = ctypes.CDLL(None, use_errno=True)
        clone = library.clonefile
        clone.argtypes = [ctypes.c_char_p, ctypes.c_char_p, ctypes.c_int]
        clone.restype = ctypes.c_int
        cloned = clone(os.fsencode(source), os.fsencode(target), 0) == 0
    if not cloned: shutil.copy2(source, target)
    target.chmod(0o700 if source.stat().st_mode & 0o111 else 0o600)


def copy_tree(source: Path, target: Path, *, preserve_links: bool, materialize_links: bool = False) -> None:
    if source.is_symlink():
        if preserve_links:
            target.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
            target.symlink_to(os.readlink(source))
            return
        if not materialize_links or not source.is_file(): raise ValueError('Only model-file symlinks can be materialized')
        return copy_file(source.resolve(strict=True), target)
    if source.is_dir():
        target.mkdir(parents=True, mode=0o700)
        for child in source.iterdir(): copy_tree(child, target / child.name, preserve_links=preserve_links, materialize_links=materialize_links)
    elif source.is_file(): copy_file(source, target)
    else: raise ValueError('Unsupported migration source object')


def assert_no_writers(source: Path) -> None:
    data = source / 'data'
    if not data.exists(): return
    result = subprocess.run(['lsof', '-Fpfan', '+D', str(data)], capture_output=True, text=True)
    if result.returncode not in (0, 1) or result.stderr.strip():
        raise RuntimeError('Cannot establish source writer state; inspect lsof before migration')
    writable = False
    for field in result.stdout.splitlines():
        if field.startswith('f'): writable = False
        elif field.startswith('a'): writable = field[1:] in {'w', 'u'}
        elif field.startswith('n') and writable:
            raise RuntimeError('Source data still has an open writer; stop the old service before migration')


def encode_toml(document: dict) -> str:
    def scalar(value):
        if isinstance(value, str): return json.dumps(value, ensure_ascii=False)
        if isinstance(value, bool): return 'true' if value else 'false'
        if isinstance(value, int): return str(value)
        if isinstance(value, float) and math.isfinite(value): return repr(value)
        if isinstance(value, list): return '[' + ', '.join(scalar(item) for item in value) + ']'
        raise ValueError('Unsupported TOML value; migration cannot silently discard settings')
    lines = []
    def table(values, parts):
        if parts: lines.append('[' + '.'.join(json.dumps(part) for part in parts) + ']')
        for key, value in values.items():
            if not isinstance(value, dict): lines.append(json.dumps(key) + ' = ' + scalar(value))
        lines.append('')
        for key, value in values.items():
            if isinstance(value, dict): table(value, [*parts, key])
    table(document, [])
    output = '\n'.join(lines)
    if tomllib.loads(output) != document: raise ValueError('Configuration serialization changed its meaning')
    return output


class AgentMigration:
    def __init__(self, source: Path, destination: Path, project: Path, *, legacy_root: Path | None = None, writer_check=assert_no_writers):
        self.source = source.expanduser().resolve()
        self.destination = destination.expanduser().resolve()
        self.project = project.expanduser().absolute()
        self.legacy_root = (legacy_root or self.source).expanduser().absolute()
        if self.destination.is_relative_to(self.source) or self.source.is_relative_to(self.destination):
            raise ValueError('Source and destination must be separate directory trees')
        self.writer_check = writer_check
        self.directory = self.destination / 'migrations'
        self.receipt_path = self.directory / 'agent-import-v1.json'

    def _inputs(self):
        config = 'maltose.toml' if (self.source / 'maltose.toml').exists() else 'myagent.toml'
        if not (self.source / config).is_file(): raise FileNotFoundError('No legacy Agent configuration found')
        return [name for name in (*TREES, config, 'wake.toml', '.env') if (self.source / name).exists()], config

    def _mapped_path(self, raw: str, *, allow_external: bool = True) -> str:
        path = Path(raw).expanduser()
        if not path.is_absolute(): path = self.legacy_root / path
        path = Path(os.path.abspath(path))
        try: relative = path.relative_to(self.legacy_root)
        except ValueError:
            if not allow_external: raise ValueError('Persistent Agent state outside the source tree needs an explicit import mapping') from None
            return str(path)  # Explicit external resources retain their configured location.
        if relative.parts and relative.parts[0] in ('data', 'documents', 'models', 'recordings'):
            return str(self.destination / relative)
        if relative == Path('wake.toml'): return str(self.destination / 'wake.toml')
        if relative.is_relative_to('tools/location_helper.app'):
            return str(self.destination / 'helpers/location_helper.app' / relative.relative_to('tools/location_helper.app'))
        raise ValueError('A legacy configuration path needs an explicit migration mapping')

    def _configure(self, payload: Path, config_name: str) -> None:
        config = tomllib.loads((payload / config_name).read_text())
        for section, keys in CONFIG_PATHS.items():
            for key in keys:
                if key in config.get(section, {}):
                    config[section][key] = self._mapped_path(config[section][key],
                        allow_external=key in {'documents_root', 'speaker_model_dir', 'location_helper'})
        config.setdefault('knowledge', {}).setdefault('queue', str(self.destination / 'data/knowledge/indexing_queue.sqlite3'))
        if 'codex_cwd' in config.get('taskbrain', {}):
            old = Path(config['taskbrain']['codex_cwd']).expanduser()
            if not old.is_absolute(): old = self.legacy_root / old
            config['taskbrain']['codex_cwd'] = str(self.project if old == self.legacy_root else old)
        wake = payload / 'wake.toml'
        if wake.exists():
            document = tomllib.loads(wake.read_text())
            settings = document.get('wake', document)
            for section in ('alibaba', 'sherpa_onnx', 'sherpa-onnx'):
                for key in ('model_dir', 'tokens', 'encoder', 'decoder', 'joiner', 'keywords_file'):
                    if key in settings.get(section, {}): settings[section][key] = self._mapped_path(settings[section][key])
            if 'python' in settings.get('alibaba', {}):
                settings['alibaba']['python'] = str(self.destination / 'environments/kws310/bin/python')
            if settings.get('fallback_config'): settings['fallback_config'] = self._mapped_path(settings['fallback_config'])
            wake.write_text(encode_toml(document)); wake.chmod(0o600)
        if config_name != 'maltose.toml': (payload / config_name).unlink()
        (payload / 'maltose.toml').write_text(encode_toml(config))
        (payload / 'maltose.toml').chmod(0o600)
        environment = payload / '.env'
        if environment.exists():
            parse_service_credentials(environment.read_text())
            environment.chmod(0o600)
        if (payload / 'tools').exists():
            (payload / 'tools').rename(payload / 'helpers')

    def _migrate_database_paths(self, payload: Path) -> dict:
        updated = {}
        settings = tomllib.loads((payload / 'maltose.toml').read_text()).get('knowledge', {})
        for key, default, table in [('metadata', 'data/knowledge/metadata.sqlite3', 'documents'), ('queue', 'data/knowledge/indexing_queue.sqlite3', 'indexing_jobs')]:
            configured = Path(settings.get(key, str(self.destination / default)))
            relative = str(configured.relative_to(self.destination))
            path = payload / relative
            if not path.exists(): continue
            with sqlite3.connect(path) as database:
                exists = database.execute('select 1 from sqlite_master where type=\'table\' and name=?', (table,)).fetchone()
                if not exists: raise RuntimeError('Knowledge database schema does not match the expected migration version')
                count = 0
                for rowid, old in database.execute(f'SELECT rowid, path FROM {table}').fetchall():
                    new = self._mapped_path(old)
                    if new != old:
                        database.execute(f'UPDATE {table} SET path=? WHERE rowid=?', (new, rowid)); count += 1
                updated[relative] = count
                if database.execute('pragma integrity_check').fetchone()[0] != 'ok': raise RuntimeError('Migrated database integrity check failed')
        return updated

    def run(self) -> dict:
        self.destination.mkdir(parents=True, exist_ok=True, mode=0o700)
        self.directory.mkdir(parents=True, exist_ok=True, mode=0o700)
        with RuntimeLease(self.destination):
            receipt = json.loads(self.receipt_path.read_text()) if self.receipt_path.exists() else None
            if receipt:
                attempt = receipt.get('attempt', '')
                valid_attempt = len(attempt) == 32 and all(character in '0123456789abcdef' for character in attempt)
                if receipt.get('schemaVersion') != 1 or receipt.get('source') != str(self.source) or receipt.get('destination') != str(self.destination) or receipt.get('legacyRoot') != str(self.legacy_root) or not valid_attempt:
                    raise RuntimeError('Existing migration receipt belongs to a different source or version')
                if receipt['phase'] == 'complete':
                    if not all((self.destination / name).exists() for name in receipt['published']):
                        raise RuntimeError('A completed migration is missing published data; inspect the backup')
                    return {'schemaVersion': 1, 'status': 'already_migrated', 'migrationID': receipt['migrationID']}
                if receipt.get('phase') not in {'copying', 'prepared', 'publishing'} or receipt.get('project') != str(self.project):
                    raise RuntimeError('Incomplete migration has a different project or unsupported phase')
            self.writer_check(self.source)
            inputs, config_name = self._inputs()
            before = {name: fingerprint(self.source / name) for name in inputs}
            if receipt and receipt['phase'] in {'prepared', 'publishing'}:
                if before != receipt['sourceFingerprint']: raise RuntimeError('Source changed after preparation; keep the staged copy and inspect before retrying')
            else:
                targets = ['data', 'documents', 'models', 'recordings', 'helpers', 'wake.toml', '.env', 'maltose.toml']
                if any((self.destination / name).exists() or (self.destination / name).is_symlink() for name in targets):
                    raise FileExistsError('Destination has existing Agent state without a completed migration; refusing to overwrite it')
                if receipt:
                    atomic_json(self.directory / receipt['attempt'] / 'interrupted-receipt.json', receipt)
                migration_id = uuid.uuid4().hex
                attempt = self.directory / migration_id
                attempt.mkdir(mode=0o700)
                receipt = {'schemaVersion': 1, 'migrationID': migration_id, 'phase': 'copying',
                    'source': str(self.source), 'legacyRoot': str(self.legacy_root), 'destination': str(self.destination),
                    'project': str(self.project),
                    'attempt': migration_id, 'sourceFingerprint': before, 'published': []}
                atomic_json(self.receipt_path, receipt)
                backup = attempt / 'backup'; backup.mkdir(mode=0o700)
                for name in inputs: copy_tree(self.source / name, backup / name, preserve_links=True)
                after = {name: fingerprint(self.source / name) for name in inputs}
                copied = {name: fingerprint(backup / name) for name in inputs}
                if before != after or before != copied: raise RuntimeError('Source changed while copying; backup retained, no app configuration published')
                payload = attempt / 'payload'; payload.mkdir(mode=0o700)
                for name in inputs: copy_tree(backup / name, payload / name, preserve_links=False, materialize_links=name == 'models')
                self._configure(payload, config_name)
                receipt['databasePathUpdates'] = self._migrate_database_paths(payload)
                receipt['payloadFingerprint'] = {p.name: fingerprint(p) for p in payload.iterdir()}
                receipt['phase'] = 'prepared'
                atomic_json(self.receipt_path, receipt)
            self.writer_check(self.source)
            payload = self.directory / receipt['attempt'] / 'payload'
            receipt['phase'] = 'publishing'; atomic_json(self.receipt_path, receipt)
            names = sorted(receipt['payloadFingerprint'], key=lambda name: (name == 'maltose.toml', name))
            for name in names:
                target, staged = self.destination / name, payload / name
                expected = receipt['payloadFingerprint'][name]
                if target.exists() or target.is_symlink():
                    if staged.exists() or fingerprint(target) != expected: raise FileExistsError('Published migration data differs from its prepared snapshot; refusing to overwrite')
                else:
                    if name in receipt['published'] or fingerprint(staged) != expected: raise RuntimeError('Prepared migration payload is missing or changed')
                    staged.rename(target)
                if name not in receipt['published']: receipt['published'].append(name)
                atomic_json(self.receipt_path, receipt)
            receipt['phase'] = 'complete'; atomic_json(self.receipt_path, receipt)
            return {'schemaVersion': 1, 'status': 'migrated', 'migrationID': receipt['migrationID'],
                'topLevelItems': len(names), 'databasePathUpdates': receipt['databasePathUpdates']}


def main():
    parser = argparse.ArgumentParser(description='Import an existing local Agent installation with private recovery backups.')
    parser.add_argument('--source', type=Path, required=True)
    parser.add_argument('--destination', type=Path, required=True)
    parser.add_argument('--project', type=Path, required=True)
    parser.add_argument('--legacy-root', type=Path)
    arguments = parser.parse_args()
    try:
        result = AgentMigration(arguments.source, arguments.destination, arguments.project, legacy_root=arguments.legacy_root).run()
    except (OSError, ValueError, RuntimeError) as error:
        parser.exit(2, f'Migration stopped: {error}\n')
    print(json.dumps(result, ensure_ascii=False))


if __name__ == '__main__': main()
