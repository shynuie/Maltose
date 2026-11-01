import json
import os
from pathlib import Path
import sqlite3
import tempfile
import tomllib
import unittest
from unittest.mock import patch

from maltose.migration import AgentMigration, encode_toml, fingerprint


class AgentMigrationTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.base = Path(temporary.name).resolve()
        self.source = self.base / 'legacy'
        self.destination = self.base / 'Maltose'
        for name in ('data', 'documents', 'models', 'recordings', 'tools/location_helper.app/Contents/MacOS'):
            (self.source / name).mkdir(parents=True, exist_ok=True)
        self.document = self.source / 'documents/note.md'
        self.document.write_text('Original document, source of truth.')
        (self.source / 'data/memory.json').write_text(json.dumps({'remembered': str(self.source) + ' is a historical user statement'}))
        for name, table in [('metadata.sqlite3', 'documents'), ('queue.sqlite3', 'indexing_jobs')]:
            with sqlite3.connect(self.source / 'data' / name) as db:
                db.execute(f'create table {table} (id text primary key, path text, state text)')
                db.execute(f'insert into {table} values (?,?,?)', ('preserved-id', str(self.document), 'indexed'))
        with sqlite3.connect(self.source / 'data/tasks.sqlite3') as db:
            db.execute('create table tasks (id text, status text)')
            db.execute('insert into tasks values (?,?)', ('task-1', 'succeeded'))
        (self.source / 'myagent.toml').write_text(encode_toml({
            'agent': {'brain': 'taskbrain', 'output_dir': 'recordings'},
            'taskbrain': {'memory': 'data/memory.json', 'tasks': 'data/tasks.sqlite3', 'codex_cwd': str(self.source), 'model': 'unchanged-model'},
            'knowledge': {'enabled': True, 'metadata': 'data/metadata.sqlite3', 'queue': 'data/queue.sqlite3', 'documents_root': 'documents'},
            'wake': {'config': 'wake.toml'},
            'environment': {'location_helper': 'tools/location_helper.app/Contents/MacOS/location_helper'},
        }))
        (self.source / 'wake.toml').write_text(encode_toml({'wake': {'provider': 'alibaba-modelscope', 'alibaba': {'model_dir': 'models/kws', 'python': '.venvs/kws310/bin/python'}}}))
        (self.source / 'models/kws').mkdir()
        (self.source / 'models/kws/model').write_bytes(b'model fixture')
        cache = self.base / 'cached-model'; cache.write_bytes(b'cached model fixture')
        (self.source / 'models/link').symlink_to(cache)
        (self.source / '.env').write_text('OPENAI_API_KEY=private-fixture')
        helper = self.source / 'tools/location_helper.app/Contents/MacOS/location_helper'
        helper.write_bytes(b'helper fixture'); helper.chmod(0o755)
        self.migration = AgentMigration(self.source, self.destination, self.base / 'project', writer_check=lambda _: None)

    def test_import_preserves_data_updates_only_operational_paths_and_is_idempotent(self):
        original = fingerprint(self.source)
        (self.destination / 'conversations').mkdir(parents=True)
        journal = self.destination / 'conversations/native.jsonl'; journal.write_text('existing journal')
        result = self.migration.run()
        self.assertEqual(result['status'], 'migrated')
        config = tomllib.loads((self.destination / 'maltose.toml').read_text())
        self.assertEqual(config['taskbrain']['model'], 'unchanged-model')
        self.assertEqual(config['taskbrain']['codex_cwd'], str(self.base / 'project'))
        self.assertEqual(config['knowledge']['documents_root'], str(self.destination / 'documents'))
        wake = tomllib.loads((self.destination / 'wake.toml').read_text())
        self.assertEqual(wake['wake']['alibaba']['python'], str(self.destination / 'environments/kws310/bin/python'))
        for name, table in [('metadata.sqlite3', 'documents'), ('queue.sqlite3', 'indexing_jobs')]:
            with sqlite3.connect(self.destination / 'data' / name) as db:
                self.assertEqual(db.execute(f'select * from {table}').fetchall(), [('preserved-id', str(self.destination / 'documents/note.md'), 'indexed')])
        self.assertEqual(fingerprint(self.source), original)
        self.assertEqual((self.destination / 'data/memory.json').read_bytes(), (self.source / 'data/memory.json').read_bytes())
        self.assertEqual(journal.read_text(), 'existing journal')
        self.assertFalse((self.destination / 'models/link').is_symlink())
        self.assertEqual((self.destination / 'models/link').read_bytes(), b'cached model fixture')
        self.assertTrue(os.access(self.destination / 'helpers/location_helper.app/Contents/MacOS/location_helper', os.X_OK))
        self.assertEqual((self.destination / '.env').stat().st_mode & 0o777, 0o600)
        (self.destination / 'documents/note.md').write_text('new user edit')
        self.assertEqual(self.migration.run()['status'], 'already_migrated')
        self.assertEqual((self.destination / 'documents/note.md').read_text(), 'new user edit')
        receipt = json.loads(self.migration.receipt_path.read_text())
        backup = self.migration.directory / receipt['attempt'] / 'backup'
        self.assertEqual((backup / 'myagent.toml').read_bytes(), (self.source / 'myagent.toml').read_bytes())
        self.source.rename(self.base / 'archived-source')
        self.assertEqual(AgentMigration(self.source, self.destination, self.base / 'project').run()['status'], 'already_migrated')

    def test_crash_after_rename_resumes_without_overwriting_or_duplicating_data(self):
        rename = Path.rename
        def interrupted(path, target):
            result = rename(path, target)
            if path.name == 'documents' and path.parent.name == 'payload': raise OSError('simulated interruption after rename')
            return result
        with patch.object(Path, 'rename', interrupted), self.assertRaises(OSError): self.migration.run()
        self.assertFalse((self.destination / 'maltose.toml').exists())
        self.assertEqual(self.migration.run()['status'], 'migrated')
        self.assertEqual((self.destination / 'documents/note.md').read_text(), self.document.read_text())

    def test_existing_state_and_writers_stop_import_without_overwriting(self):
        (self.destination / 'data').mkdir(parents=True)
        existing = self.destination / 'data/important'; existing.write_text('keep')
        with self.assertRaises(FileExistsError): self.migration.run()
        self.assertEqual(existing.read_text(), 'keep')
        other = AgentMigration(self.source, self.base / 'other', self.base / 'project', writer_check=lambda _: (_ for _ in ()).throw(RuntimeError('writer active')))
        with self.assertRaisesRegex(RuntimeError, 'writer active'): other.run()
        self.assertFalse((other.destination / 'maltose.toml').exists())

    def test_source_change_during_copy_retains_backup_then_can_restart(self):
        from maltose import migration
        copy = migration.copy_tree
        changed = False
        def concurrent_change(source, target, **kwargs):
            nonlocal changed
            result = copy(source, target, **kwargs)
            if source == self.source / 'documents' and not changed:
                changed = True; self.document.write_text('new source revision')
            return result
        with patch.object(migration, 'copy_tree', concurrent_change), self.assertRaisesRegex(RuntimeError, 'Source changed'):
            self.migration.run()
        first = json.loads(self.migration.receipt_path.read_text())
        self.assertFalse((self.destination / 'maltose.toml').exists())
        self.assertEqual(self.migration.run()['status'], 'migrated')
        self.assertTrue((self.migration.directory / first['attempt'] / 'interrupted-receipt.json').exists())
        self.assertEqual((self.destination / 'documents/note.md').read_text(), 'new source revision')

    def test_symlink_document_cannot_expand_the_original_knowledge_boundary(self):
        secret = self.base / 'outside'; secret.write_text('outside the document root')
        (self.source / 'documents/escape').symlink_to(secret)
        with self.assertRaisesRegex(ValueError, 'model-file'): self.migration.run()
        self.assertFalse((self.destination / 'maltose.toml').exists())

    def test_nested_destination_and_unsupported_toml_are_rejected(self):
        with self.assertRaises(ValueError): AgentMigration(self.source, self.source / 'nested', self.base / 'project')
        settings = {'quoted.section': {'quoted key': 'line\n"quoted"\\text', 'bool': True, 'values': [1, 2.5, 'three']}}
        self.assertEqual(tomllib.loads(encode_toml(settings)), settings)
        with self.assertRaises(ValueError): encode_toml({'unsupported': None})
