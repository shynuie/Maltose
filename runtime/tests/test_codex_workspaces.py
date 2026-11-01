import json
import os
from pathlib import Path
import subprocess
import tempfile
import unittest
from unittest.mock import patch
import uuid

from maltose.codex.workspaces import CodexWorkspaceError, CodexWorkspaceManager


class CodexWorkspaceTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory(prefix='maltose-codex-workspaces-')
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name).resolve()
        self.repo = self.root / 'source'; self.repo.mkdir()
        self.git('init', '-q')
        self.git('config', 'user.name', 'Fixture')
        self.git('config', 'user.email', 'fixture@example.invalid')
        (self.repo / '.gitignore').write_text('.env\nbuild/\n')
        (self.repo / 'code.py').write_text('original\n')
        (self.repo / 'deleted.py').write_text('removed later\n')
        (self.repo / 'binary.dat').write_bytes(b'\x00\xff')
        self.git('add', '.')
        self.git('commit', '-qm', 'Fixture baseline')
        self.manager = CodexWorkspaceManager(self.root / 'managed', authorized_repositories=(self.repo,))

    def git(self, *arguments):
        return subprocess.run(['/usr/bin/git', '-C', str(self.repo), *arguments], check=True,
                              stdout=subprocess.PIPE, stderr=subprocess.PIPE).stdout

    def prepare(self): return self.manager.prepare(self.repo, str(uuid.uuid4()))

    def test_dirty_staged_untracked_deletions_and_links_preserved_without_touching_source_index(self):
        (self.repo / 'code.py').write_text('staged edit\n'); self.git('add', 'code.py')
        (self.repo / 'code.py').write_text('latest unstaged edit\n')
        self.git('rm', '-q', 'deleted.py')
        (self.repo / 'new file.py').write_text('untracked\n')
        (self.repo / '.env').write_text('PRIVATE_FIXTURE=not-a-real-credential\n')
        (self.repo / 'link.py').symlink_to('code.py')
        os.chmod(self.repo / 'code.py', 0o755)
        status = self.git('status', '--porcelain=v1', '-z', '--untracked-files=all')
        index = self.git('diff', '--cached', '--binary')
        head = self.git('rev-parse', 'HEAD')
        receipt = self.prepare(); workspace = Path(receipt['worktree'])
        self.assertEqual((workspace / 'code.py').read_text(), 'latest unstaged edit\n')
        self.assertEqual((workspace / 'new file.py').read_text(), 'untracked\n')
        self.assertFalse((workspace / 'deleted.py').exists())
        self.assertFalse((workspace / '.env').exists())
        self.assertTrue((workspace / 'link.py').is_symlink())
        self.assertEqual(os.readlink(workspace / 'link.py'), 'code.py')
        self.assertTrue((workspace / 'code.py').stat().st_mode & 0o100)
        self.assertEqual(self.git('status', '--porcelain=v1', '-z', '--untracked-files=all'), status)
        self.assertEqual(self.git('diff', '--cached', '--binary'), index)
        self.assertEqual(self.git('rev-parse', 'HEAD'), head)
        self.assertEqual(self.manager.changes(receipt['taskID'])['changes'], [])

    def test_report_attributes_only_agent_changes_against_working_baseline_not_head(self):
        (self.repo / 'code.py').write_text('user edit\n')
        receipt = self.prepare(); workspace = Path(receipt['worktree'])
        (workspace / 'code.py').write_text('user edit\nagent addition\n')
        (workspace / 'new.py').write_text('new agent file\n')
        (workspace / 'binary.dat').write_bytes(b'\x00\x01')
        (workspace / '.env').write_text('ignored private fixture')
        changes = {entry['path']: entry for entry in self.manager.changes(receipt['taskID'])['changes']}
        self.assertEqual(set(changes), {'code.py', 'new.py', 'binary.dat'})
        self.assertIn('+agent addition', changes['code.py']['diff'])
        self.assertNotIn('-original', changes['code.py']['diff'])
        self.assertTrue(changes['binary.dat']['binary'])
        self.assertEqual((self.repo / 'code.py').read_text(), 'user edit\n')
        bounded = self.manager.changes(receipt['taskID'], max_diff_chars=8)
        self.assertLessEqual(sum(len(entry.get('diff', '')) for entry in bounded['changes']), 8)
        self.assertTrue(any(entry.get('truncated') for entry in bounded['changes']))

    def test_authorization_target_reuse_nested_root_and_special_files_are_rejected(self):
        other = self.root / 'other'; other.mkdir()
        with self.assertRaises(PermissionError): self.manager.prepare(other, str(uuid.uuid4()))
        with self.assertRaises(CodexWorkspaceError): self.manager.prepare(self.repo, '../escape')
        nested = CodexWorkspaceManager(self.repo / 'managed', authorized_repositories=(self.repo,))
        with self.assertRaises(CodexWorkspaceError): nested.prepare(self.repo, str(uuid.uuid4()))
        receipt = self.prepare()
        with self.assertRaises(FileExistsError): self.manager.prepare(self.repo, receipt['taskID'])
        (self.repo / 'code.py').unlink()
        os.mkfifo(self.repo / 'code.py')
        with self.assertRaises(CodexWorkspaceError): self.prepare()

    def test_source_edit_during_copy_keeps_incomplete_attempt_and_never_overwrites_it(self):
        original = self.manager._snapshot
        def snapshot(repository, destinations=()):
            result = original(repository, destinations)
            if destinations: (self.repo / 'code.py').write_text('concurrent user edit\n')
            return result
        task_id = str(uuid.uuid4())
        with patch.object(self.manager, '_snapshot', side_effect=snapshot), self.assertRaises(CodexWorkspaceError):
            self.manager.prepare(self.repo, task_id)
        receipt = json.loads((self.manager.storage_root / task_id / 'receipt.json').read_text())
        self.assertEqual(receipt['phase'], 'incomplete')
        self.assertTrue(Path(receipt['worktree']).is_dir())
        self.assertEqual((self.repo / 'code.py').read_text(), 'concurrent user edit\n')
        with self.assertRaises(CodexWorkspaceError): self.manager.changes(task_id)

    def test_baseline_integrity_and_receipt_paths_checked_before_results(self):
        receipt = self.prepare()
        baseline = Path(receipt['baseline'])
        (baseline / 'code.py').write_text('tampered\n')
        with self.assertRaises(CodexWorkspaceError): self.manager.changes(receipt['taskID'])
        path = self.manager.storage_root / receipt['taskID'] / 'receipt.json'
        forged = dict(receipt, worktree=str(self.repo)); path.write_text(json.dumps(forged))
        with self.assertRaises(CodexWorkspaceError): self.manager.changes(receipt['taskID'])

    def test_checkout_filters_and_hooks_are_not_executed(self):
        marker = self.root / 'hook-ran'
        hook = self.repo / '.git/hooks/post-checkout'
        hook.write_text(f'#!/bin/sh\ntouch "{marker}"\n'); hook.chmod(0o755)
        filter_marker = self.root / 'filter-ran'
        self.git('config', 'filter.fixture.smudge', f'touch "{filter_marker}"')
        (self.repo / '.gitattributes').write_text('code.py filter=fixture\n')
        self.git('add', '.gitattributes'); self.git('commit', '-qm', 'Fixture filter metadata')
        receipt = self.prepare()
        self.assertEqual(receipt['phase'], 'ready')
        self.assertFalse(marker.exists())
        self.assertFalse(filter_marker.exists())

    def test_baseline_symlink_and_receipt_traversal_cannot_widen_reads(self):
        receipt = self.prepare(); baseline = Path(receipt['baseline'])
        backup = baseline.with_name('baseline-backup'); baseline.rename(backup)
        baseline.symlink_to(self.repo, target_is_directory=True)
        with self.assertRaises(CodexWorkspaceError): self.manager.changes(receipt['taskID'])
        baseline.unlink(); backup.rename(baseline)
        receipt['entries']['../../outside'] = receipt['entries']['code.py']
        path = self.manager.storage_root / receipt['taskID'] / 'receipt.json'
        path.write_text(json.dumps(receipt))
        with self.assertRaises(CodexWorkspaceError): self.manager.changes(receipt['taskID'])

    def test_source_links_cannot_make_agent_workspace_write_into_original_or_external_files(self):
        outside = self.root / 'outside'; outside.write_text('private fixture')
        link = self.repo / 'unsafe-link'
        for target in (str(self.repo / 'code.py'), '../outside', '.git/config'):
            link.symlink_to(target)
            with self.assertRaises(CodexWorkspaceError): self.prepare()
            link.unlink()
        self.assertEqual(outside.read_text(), 'private fixture')
        self.assertEqual((self.repo / 'code.py').read_text(), 'original\n')

    def test_foundation_uppercase_uuid_maps_to_same_workspace_and_receipt(self):
        identity = str(uuid.uuid4())
        receipt = self.manager.prepare(self.repo, identity.upper())
        self.assertEqual(receipt['taskID'], identity)
        self.assertEqual(self.manager.inspect(identity), self.manager.inspect(identity.upper()))
        self.assertEqual(self.manager.changes(identity.upper())['taskID'], identity)
        with self.assertRaises(FileExistsError): self.manager.prepare(self.repo, identity)


if __name__ == '__main__': unittest.main()
