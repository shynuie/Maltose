import base64
import hashlib
from pathlib import Path
import tempfile
from types import SimpleNamespace
import unittest

from maltose.filesystem.paths import FilesystemRoot, PathResolver
from maltose.filesystem.policy import PolicyEngine, WorkingRoot
from maltose.filesystem.service import FileService
from maltose.ui.native_files import NativePanelFileAdapter


class NativePanelFileTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name).resolve()
        resolver = PathResolver({
            'workspace': FilesystemRoot('workspace', self.root, read=True, write=True),
            'private': FilesystemRoot('private', self.root / 'private', read=False),
        }, protected_paths=('.env',))
        self.service = FileService(resolver, PolicyEngine(resolver, max_read_bytes=128, working_root=WorkingRoot('workspace')))
        self.calls = []
        self.bridge = SimpleNamespace(file_service=self.service, call_panel=self.call_panel)
        self.adapter = NativePanelFileAdapter(self.bridge)
        self.export = {'data': base64.b64encode(b'flow snapshot').decode(), 'documentID': 'doc', 'fingerprint': 'revision'}

    def call_panel(self, command, *, file_transfer):
        self.calls.append((command, file_transfer))
        return {'ok': True, 'result': self.export if file_transfer['mode'] == 'export' else {}}

    def test_binary_read_sends_bytes_without_opening_the_path_in_the_app(self):
        path = self.root / 'image.png'
        path.write_bytes(b'\x89PNG\xff\x00')
        result = self.adapter.call('image_add_file', {'panelID': 'gallery', 'path': str(path)})
        self.assertTrue(result['ok'])
        self.assertEqual(base64.b64decode(self.calls[0][1]['data']), path.read_bytes())
        with self.assertRaises(UnicodeDecodeError): self.service.read_file('workspace', 'image.png')

    def test_limits_protected_paths_links_and_most_specific_root_are_enforced(self):
        (self.root / 'private').mkdir()
        for name in ['private/secret', '.env', 'large']:
            (self.root / name).write_bytes(b'x' * (129 if name == 'large' else 1))
        (self.root / 'link').symlink_to(self.root / 'private/secret')
        for path in ['private/secret', '.env', 'large', 'link', '../outside', 'relative']:
            with self.subTest(path=path), self.assertRaises((PermissionError, ValueError)):
                self.adapter.call('chart_open_csv', {'panelID': 'chart', 'path': path if path == 'relative' else str(self.root / path)})
        self.assertEqual(self.calls, [])

    def test_save_uses_snapshot_then_policy_write_and_acknowledges_exact_revision(self):
        path = self.root / 'diagram.maltoseflow.json'
        result = self.adapter.call('flowchart_save', {'panelID': 'canvas', 'path': str(path)})
        self.assertTrue(result['ok'])
        self.assertEqual(path.read_bytes(), b'flow snapshot')
        self.assertEqual([call[1]['mode'] for call in self.calls], ['export', 'saved'])
        self.assertEqual(self.calls[1][1]['documentID'], 'doc')
        self.assertEqual(self.calls[1][1]['fileSHA256'], hashlib.sha256(path.read_bytes()).hexdigest())

    def test_save_rejects_unread_or_externally_changed_existing_files(self):
        path = self.root / 'diagram.maltoseflow.json'
        path.write_bytes(b'existing')
        arguments = {'panelID': 'canvas', 'path': str(path)}
        with self.assertRaises(ValueError): self.adapter.call('flowchart_save', arguments)
        self.export['knownFileSHA256'] = hashlib.sha256(b'old revision').hexdigest()
        with self.assertRaises(RuntimeError): self.adapter.call('flowchart_save', arguments)
        self.assertEqual(path.read_bytes(), b'existing')
        self.assertTrue(all(call[1]['mode'] == 'export' for call in self.calls))
        result = self.adapter.call('flowchart_save', {**arguments, 'expectedSHA256': hashlib.sha256(b'existing').hexdigest()})
        self.assertTrue(result['ok'])
        self.assertNotIn('expectedSHA256', self.calls[-2][0]['flowchart_save'])

    def test_readonly_save_does_not_export_private_panel_content(self):
        with self.assertRaises(PermissionError):
            self.adapter.call('flowchart_save', {'panelID': 'canvas', 'path': str(self.root / 'private/new.maltoseflow.json')})
        self.assertEqual(self.calls, [])

    def test_ui_acknowledgement_failure_does_not_claim_successful_file_write_failed(self):
        def call(command, *, file_transfer):
            if file_transfer['mode'] == 'saved': return {'ok': False, 'error': {'code': 'not_found'}}
            return self.call_panel(command, file_transfer=file_transfer)
        self.bridge.call_panel = call
        path = self.root / 'diagram.maltoseflow.json'
        result = self.adapter.call('flowchart_save', {'panelID': 'canvas', 'path': str(path)})
        self.assertTrue(result['ok'])
        self.assertFalse(result['result']['panelAcknowledgement']['ok'])
        self.assertEqual(path.read_bytes(), b'flow snapshot')
