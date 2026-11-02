import fcntl
import importlib.util
import json
import os
from pathlib import Path
import subprocess
import tempfile
import tomllib
import unittest
from unittest.mock import patch

from maltose.migration import encode_toml
from maltose.runtime.ownership import RuntimeLease

spec=importlib.util.spec_from_file_location('maltose_project_relocation',Path(__file__).resolve().parents[1]/'dev/tools/relocate_project.py')
relocation=importlib.util.module_from_spec(spec)
spec.loader.exec_module(relocation)


class ProjectRelocationTests(unittest.TestCase):
    def setUp(self):
        temporary=tempfile.TemporaryDirectory(); self.addCleanup(temporary.cleanup)
        self.base=Path(temporary.name).resolve(); self.source=self.base/'Maltose_UI'; self.target=self.base/'Maltose'; self.support=self.base/'Support'
        self.source.mkdir(); self.support.mkdir(); (self.source/'runtime').mkdir()
        (self.source/'Package.swift').write_text('// fixture')
        (self.source/'runtime/pyproject.toml').write_text('[project]\nname="fixture"\n')
        (self.source/'.gitignore').write_text('.cache/\n.venv/\n')
        (self.source/'deleted.txt').write_text('preserved deletion')
        self.git('init','--quiet'); self.git('add','.')
        self.git('-c','user.name=Fixture','-c','user.email=fixture@example.invalid','commit','--quiet','-m','fixture')
        (self.source/'Package.swift').write_text('// user dirty change')
        (self.source/'deleted.txt').unlink(); (self.source/'untracked.txt').write_text('preserved untracked')
        (self.source/'.cache').mkdir(); (self.source/'.cache/private.bin').write_bytes(b'private-fixture\0')
        (self.source/'runtime/.venv').mkdir(); (self.source/'runtime/.venv/marker').write_text('rebuild, never rewrite in place')
        self.config=dict(taskbrain=dict(codex_cwd=str(self.source),model='unchanged-model'),
            knowledge=dict(documents_root=str(self.base/'Documents')),agent=dict(brain='taskbrain'),
            note=dict(history=str(self.source)+' was the original path',unrelated=str(self.source)+'_other'))
        self.save_config(self.config)
        self.operation=relocation.ProjectRelocation(self.source,self.target,self.support)

    def git(self,*arguments):
        return subprocess.check_output(['/usr/bin/git','-c','core.hooksPath=/dev/null','-c','core.fsmonitor=false','-C',str(self.source),*arguments],stderr=subprocess.DEVNULL)

    def save_config(self,value):
        path=self.support/'maltose.toml'; path.write_text(encode_toml(value)); path.chmod(0o600)

    def test_inspect_is_read_only_and_relocation_preserves_head_dirty_files_ignored_data_and_configuration(self):
        before=relocation.snapshot(self.source); config_before=(self.support/'maltose.toml').read_bytes()
        plan=self.operation.inspect()
        self.assertEqual(before,relocation.snapshot(self.source)); self.assertFalse(self.operation.receipt.exists())
        self.assertFalse(self.target.exists()); self.assertEqual((self.support/'maltose.toml').read_bytes(),config_before)
        result=self.operation.run()
        self.assertEqual(result['phase'],'relocated'); self.assertTrue(result['developmentEnvironmentRequiresRebuild'])
        self.assertTrue(self.source.is_symlink()); self.assertFalse(self.target.is_symlink())
        self.assertEqual(before,relocation.snapshot(self.target))
        self.assertEqual((self.target/'.cache/private.bin').read_bytes(),b'private-fixture\0')
        self.assertEqual((self.target/'runtime/.venv/marker').read_text(),'rebuild, never rewrite in place')
        updated=tomllib.loads((self.support/'maltose.toml').read_text()); expected={**self.config,'taskbrain':{**self.config['taskbrain'],'codex_cwd':str(self.target)}}
        self.assertEqual(updated,expected)
        self.assertEqual((self.operation.directory/'config-before.toml').read_bytes(),config_before)
        self.assertEqual(plan['before'],before)
        self.assertEqual(self.operation.run(),result)

    def test_destination_is_never_replaced_even_if_it_appears_after_inspection(self):
        self.operation.inspect(); self.target.mkdir(); (self.target/'user').write_text('preserve')
        with self.assertRaises(FileExistsError): self.operation.run()
        self.assertEqual((self.target/'user').read_text(),'preserve'); self.assertFalse(self.source.is_symlink())
        with self.assertRaises(OSError): relocation.rename_exclusive(self.source,self.target)
        self.assertEqual((self.source/'Package.swift').read_text(),'// user dirty change')

    def test_kernel_runtime_and_product_store_leases_both_prevent_moving_an_active_installation(self):
        with RuntimeLease(self.support):
            with self.assertRaises(RuntimeError): self.operation.run()
        collaboration=self.support/'collaboration'; collaboration.mkdir(exist_ok=True)
        with (collaboration/'tasks.json.lock').open('a+b') as lease:
            fcntl.flock(lease,fcntl.LOCK_EX|fcntl.LOCK_NB)
            with self.assertRaises(BlockingIOError): self.operation.run()
        self.assertTrue(self.source.is_dir()); self.assertFalse(self.target.exists())

    def test_interruption_after_atomic_move_resumes_using_directory_identity_without_reimporting(self):
        with patch.object(relocation.os,'symlink',side_effect=OSError('fixture interruption')):
            with self.assertRaises(OSError): self.operation.run()
        self.assertFalse(self.source.exists()); self.assertTrue(self.target.is_dir())
        self.assertEqual(json.loads(self.operation.receipt.read_text())['phase'],'prepared')
        self.assertEqual(self.operation.run()['phase'],'relocated')
        self.assertEqual((self.source/'.cache/private.bin').read_bytes(),b'private-fixture\0')

    def test_manual_config_change_during_move_is_never_overwritten(self):
        original=relocation.rename_exclusive
        def move_then_edit(source,target):
            original(source,target)
            self.save_config({**self.config,'agent':dict(brain='manual-change')})
        with patch.object(relocation,'rename_exclusive',side_effect=move_then_edit):
            with self.assertRaisesRegex(ValueError,'Configuration changed'): self.operation.run()
        self.assertEqual(tomllib.loads((self.support/'maltose.toml').read_text())['agent']['brain'],'manual-change')
        with self.assertRaisesRegex(ValueError,'Configuration changed'): self.operation.run()
        self.assertTrue(self.target.is_dir()); self.assertTrue(self.source.is_symlink())

    def test_unknown_operational_paths_and_saved_tasks_are_not_blindly_rewritten(self):
        self.save_config({**self.config,'knowledge':dict(documents_root=str(self.source/'private-documents'))})
        with self.assertRaisesRegex(ValueError,'Additional operational'): self.operation.run()
        self.save_config(self.config)
        directory=self.support/'collaboration'; directory.mkdir(exist_ok=True)
        path=directory/'tasks.json'; path.write_text(json.dumps(dict(tasks=[dict(id='task')]))); path.chmod(0o600)
        with self.assertRaisesRegex(ValueError,'Saved development tasks'): self.operation.run()
        self.assertFalse(self.target.exists()); self.assertEqual(json.loads(path.read_text())['tasks'],[dict(id='task')])

    def test_private_config_permissions_symbolic_sources_and_nested_support_are_rejected(self):
        (self.support/'maltose.toml').chmod(0o644)
        with self.assertRaises(PermissionError): self.operation.inspect()
        (self.support/'maltose.toml').chmod(0o600)
        alias=self.base/'alias'; alias.symlink_to(self.source,target_is_directory=True)
        with self.assertRaises(ValueError): relocation.ProjectRelocation(alias,self.target,self.support).inspect()
        with self.assertRaises(ValueError): relocation.ProjectRelocation(self.source,self.target,self.source/'Support')

    def test_stale_prepared_source_and_foreign_receipt_are_not_resumed(self):
        with patch.object(relocation,'rename_exclusive',side_effect=OSError('before rename')):
            with self.assertRaises(OSError): self.operation.run()
        (self.source/'untracked.txt').write_text('new user edit')
        with self.assertRaisesRegex(ValueError,'Checkout or configuration changed'): self.operation.run()
        state=json.loads(self.operation.receipt.read_text()); state['target']=str(self.base/'foreign')
        self.operation.receipt.write_text(json.dumps(state))
        with self.assertRaisesRegex(ValueError,'another operation'): self.operation.run()
        self.assertFalse(self.target.exists())

    def test_symbolic_migration_parent_cannot_redirect_private_backup(self):
        outside=self.base/'outside'; outside.mkdir()
        (self.support/'migrations').symlink_to(outside,target_is_directory=True)
        with self.assertRaises(PermissionError): self.operation.run()
        self.assertFalse(list(outside.iterdir())); self.assertFalse(self.target.exists())


if __name__=='__main__': unittest.main()
