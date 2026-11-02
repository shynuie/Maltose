import json
import os
from pathlib import Path
import signal
import subprocess
import sys
import tempfile
import time
import unittest

import psutil

from maltose.codex.lifetime import Descendants, Identity


def stopped(pid):
    try: return psutil.Process(pid).status()==psutil.STATUS_ZOMBIE
    except psutil.NoSuchProcess: return True


class CodexLifetimeTests(unittest.TestCase):
    def test_identity_mismatch_never_signals_a_reused_or_unrelated_process(self):
        child=subprocess.Popen([sys.executable,'-c','import time; time.sleep(30)'])
        try:
            record=Identity.read(child.pid)
            mismatch=Identity(record.pid,record.created+1)
            self.assertIsNone(mismatch.process())
            self.assertTrue(Descendants(mismatch).stop())
            self.assertIsNone(child.poll())
        finally:
            child.kill(); child.wait(timeout=3)

    def test_tracked_detached_term_resistant_child_is_stopped_after_root_exits(self):
        program="""import json,subprocess,sys,time
child=subprocess.Popen([sys.executable,'-c','import signal,time; signal.signal(signal.SIGHUP,signal.SIG_IGN); signal.signal(signal.SIGTERM,signal.SIG_IGN); time.sleep(30)'],start_new_session=True,stdin=subprocess.DEVNULL,stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL)
print(json.dumps(dict(child=child.pid)),flush=True)
for line in sys.stdin: pass
"""
        root=subprocess.Popen([sys.executable,'-u','-c',program],stdin=subprocess.PIPE,stdout=subprocess.PIPE,text=True)
        unrelated=subprocess.Popen([sys.executable,'-c','import time; time.sleep(30)'])
        child=None
        try:
            child=Identity.read(json.loads(root.stdout.readline())['child'])
            tracker=Descendants(Identity.read(root.pid)); tracker.collect()
            self.assertIn(child.pid,tracker.known)
            root.kill(); root.wait(timeout=3)
            self.assertTrue(tracker.stop())
            self.assertIsNone(child.process()); self.assertIsNone(unrelated.poll())
        finally:
            if child is not None and child.process() is not None: child.process().kill()
            if root.poll() is None: root.kill()
            root.wait(timeout=3); root.stdin.close(); root.stdout.close()
            unrelated.kill(); unrelated.wait(timeout=3)

    def test_runner_guard_survives_server_group_kill_and_holds_eof_until_cleanup(self):
        program="""import json,subprocess,sys,time
child=subprocess.Popen([sys.executable,'-c','import signal,time; signal.signal(signal.SIGHUP,signal.SIG_IGN); signal.signal(signal.SIGTERM,signal.SIG_IGN); time.sleep(30)'],start_new_session=True,stdin=subprocess.DEVNULL,stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL)
time.sleep(.2)
print(json.dumps(dict(fixtureChild=child.pid)),flush=True)
for line in sys.stdin: pass
"""
        root=subprocess.Popen([sys.executable,'-m','maltose.codex.runner',sys.executable,'-u','-c',program],stdin=subprocess.PIPE,stdout=subprocess.PIPE,stderr=subprocess.PIPE,text=True)
        child=guardian=None
        try:
            registration=json.loads(root.stdout.readline())
            self.assertEqual(registration['method'],'maltose/lifetime/started')
            guardian=Identity.read(registration['params']['guardianPID'])
            self.assertNotEqual(os.getpgid(guardian.pid),root.pid)
            child=Identity.read(json.loads(root.stdout.readline())['fixtureChild'])
            self.assertNotEqual(os.getpgid(child.pid),root.pid)
            os.killpg(root.pid,signal.SIGKILL)
            output,diagnostics=root.communicate(timeout=8)
            events=[json.loads(line) for line in output.splitlines() if line.strip()]
            self.assertEqual([value['method'] for value in events],['maltose/lifetime/cleaned'],diagnostics)
            self.assertEqual(events[0]['params']['token'],registration['params']['token'])
            self.assertIsNone(child.process()); self.assertIsNone(guardian.process())
        finally:
            for record in (child,guardian):
                if record is not None and record.process() is not None: record.process().kill()
            if root.poll() is None: root.kill()
            root.wait(timeout=3)
            for stream in (root.stdin,root.stdout,root.stderr):
                if stream and not stream.closed: stream.close()


if __name__=='__main__': unittest.main()
