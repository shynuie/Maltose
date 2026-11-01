import os
from pathlib import Path
import subprocess
import sys
import tempfile
import time
from types import SimpleNamespace
import unittest
from unittest.mock import patch

from maltose.runtime.ownership import ManagedWorker, RuntimeLease
from maltose.voice.wake import GainWakeWordDetector, HighPassWakeWordDetector, FallbackWakeWordDetector


class NativeOwnershipTests(unittest.TestCase):
    def test_managed_installer_cannot_mutate_environments_used_by_a_live_runtime(self):
        script = Path(__file__).resolve().parents[2] / 'scripts/setup-managed-runtime.sh'
        with tempfile.TemporaryDirectory() as directory, RuntimeLease(Path(directory)):
            result = subprocess.run(['/bin/sh', str(script), directory], capture_output=True, text=True, timeout=5)
            self.assertEqual(result.returncode, 2)
            self.assertIn('Quit Maltose', result.stderr)
            self.assertFalse((Path(directory) / 'environments').exists())

    def test_kernel_lease_rejects_duplicate_and_releases_after_crash(self):
        with tempfile.TemporaryDirectory() as directory:
            program = 'from pathlib import Path; from maltose.runtime.ownership import RuntimeLease; import time; lease=RuntimeLease(Path(__import__("sys").argv[1])); print("leased",flush=True); time.sleep(20)'
            child = subprocess.Popen([sys.executable, '-c', program, directory], stdout=subprocess.PIPE, text=True)
            try:
                self.assertEqual(child.stdout.readline().strip(), 'leased')
                with self.assertRaises(RuntimeError): RuntimeLease(Path(directory))
            finally:
                child.kill(); child.wait(timeout=3); child.stdout.close()
            with RuntimeLease(Path(directory)): pass
            self.assertTrue((Path(directory) / '.native-runtime.lock').exists(), 'A stale pathname must not prevent a new lease')

    def test_managed_worker_closes_cooperatively_and_reaps_child(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / 'lifetime_fixture.py').write_text('import sys,time\nfrom pathlib import Path\np=Path(sys.argv[1]); p.write_text("started")\ntry:\n while True: time.sleep(.05)\nfinally: p.write_text("closed")\n')
            marker = root / 'marker'
            with patch.dict(os.environ, {'PYTHONPATH': str(root) + os.pathsep + os.environ.get('PYTHONPATH', '')}):
                worker = ManagedWorker('lifetime_fixture', [str(marker)])
                try:
                    deadline = time.monotonic() + 5
                    while not marker.exists() and time.monotonic() < deadline: time.sleep(.01)
                    self.assertTrue(marker.exists())
                finally: worker.close()
            self.assertEqual(marker.read_text(), 'closed')
            self.assertEqual(worker.process.returncode, 0)

    def test_normalization_and_fallback_owners_close_workers_once(self):
        closed = []
        primary = SimpleNamespace(close=lambda: closed.append('primary'))
        fallback = SimpleNamespace(close=lambda: closed.append('fallback'))
        detector = HighPassWakeWordDetector(GainWakeWordDetector(FallbackWakeWordDetector(primary, fallback)))
        detector.close(); detector.close()
        self.assertEqual(closed, ['primary', 'fallback'])

    def test_managed_worker_exits_when_parent_crashes(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / 'lifetime_fixture.py').write_text('import sys,time\nfrom pathlib import Path\np=Path(sys.argv[1]); p.write_text("started")\ntry:\n while True: time.sleep(.05)\nfinally: p.write_text("closed")\n')
            marker = root / 'marker'
            program = '''import os,sys,time
from pathlib import Path
from maltose.runtime.ownership import ManagedWorker
worker=ManagedWorker('lifetime_fixture', [sys.argv[1]])
deadline=time.monotonic()+5
while not Path(sys.argv[1]).exists() and time.monotonic()<deadline: time.sleep(.01)
os._exit(23)
'''
            environment = {**os.environ, 'PYTHONPATH': str(root) + os.pathsep + os.environ.get('PYTHONPATH', '')}
            result = subprocess.run([sys.executable, '-c', program, str(marker)], env=environment, capture_output=True, timeout=10)
            self.assertEqual(result.returncode, 23)
            self.assertEqual(marker.read_text(), 'closed', 'Worker must run cleanup after parent pipe EOF')

    def test_actual_empty_knowledge_watcher_stops_and_closes_its_databases(self):
        import sqlite3
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            queue = root / 'queue.sqlite3'
            worker = ManagedWorker('maltose.knowledge.cli', [
                '--documents-root', str(root / 'documents'), '--metadata', str(root / 'metadata.sqlite3'),
                '--vectors', str(root / 'vectors.lancedb'), '--queue', str(queue), 'watch', '--poll-interval', '.05'])
            try:
                deadline = time.monotonic() + 10
                while not queue.exists() and worker.process.poll() is None and time.monotonic() < deadline: time.sleep(.02)
                self.assertTrue(queue.exists())
            finally: worker.close()
            self.assertEqual(worker.process.returncode, 0)
            with sqlite3.connect(queue) as database:
                self.assertEqual(database.execute('pragma integrity_check').fetchone()[0], 'ok')

    def test_cli_initialization_failure_closes_wake_worker(self):
        from maltose.agent import cli
        closed = []
        wake = SimpleNamespace(close=lambda: closed.append(True))
        config = SimpleNamespace(sherpa_onnx=None, normalization_mode='none')
        with patch.object(sys, 'argv', ['maltose', '--config', '/not-present/native-test.toml', '--brain', 'echo', '--speaker-recognition', 'none', '--wake-config', 'fake']), \
             patch.object(cli, 'load_wake_word_config', return_value=config), \
             patch.object(cli, 'create_wake_word_detector', return_value=wake), \
             patch.object(cli, 'VoiceAgent', side_effect=RuntimeError('initialization failed')):
            with self.assertRaisesRegex(RuntimeError, 'initialization failed'): cli.main()
        self.assertEqual(closed, [True])
