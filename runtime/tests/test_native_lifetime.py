"""Real process faults while the native main runtime is busy, without audio."""
import json
import os
from pathlib import Path
import queue
import signal
import subprocess
import sys
import tempfile
import threading
import time
import unittest

from maltose.runtime.ownership import RuntimeLease
from maltose.runtime.processes import Identity


PROGRAM = '''import sys,time,subprocess
from pathlib import Path
from maltose.agent.brain import EchoBrain
base=Path(sys.argv[1])
def blocked(self,text,context=None):
 if mode=='worker':
  child=subprocess.Popen([sys.executable,'-c',"import os,json,signal,time,sys;from pathlib import Path;signal.signal(signal.SIGTERM,signal.SIG_IGN);signal.signal(signal.SIGHUP,signal.SIG_IGN);Path(sys.argv[1]).write_text(str(os.getpid()));time.sleep(60)",str(base/'worker-pid')],start_new_session=True,stdin=subprocess.DEVNULL,stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL)
  deadline=time.monotonic()+5
  while not (base/'worker-pid').exists() and time.monotonic()<deadline:time.sleep(.01)
  time.sleep(.25)
 (base/'entered').touch()
 time.sleep(60)
 (base/'late-write').touch()
 return 'late answer'
EchoBrain.process=blocked
mode=sys.argv[2]
sys.argv=['maltose','--brain','echo','--native-text-only','--config',str(base/'none.toml')]
from maltose.desktop import main
main()
'''
HOST = '''import json,subprocess,sys,time
child=subprocess.Popen([sys.executable,sys.argv[1],sys.argv[2],sys.argv[3]],stdin=sys.stdin,stdout=sys.stdout,stderr=sys.stderr)
print(json.dumps({'fixtureRootPID':child.pid}),flush=True)
time.sleep(60)
'''


class BusyRuntime:
    def __init__(self, directory, *, host=False, worker=True):
        self.directory = Path(directory)
        program = self.directory/'fixture.py'; program.write_text(PROGRAM)
        self.log = (self.directory/'runtime.log').open('w')
        mode = 'worker' if worker else 'no-worker'
        arguments = [sys.executable, '-u', '-c', HOST, str(program), str(self.directory), mode] if host else [sys.executable, '-u', str(program), str(self.directory), mode]
        environment = {**os.environ, 'PYTHONPATH': str(Path(__file__).resolve().parents[1])}
        self.process = subprocess.Popen(arguments, stdin=subprocess.PIPE, stdout=subprocess.PIPE,
            stderr=self.log, text=True, cwd=self.directory, env=environment)
        self.parent = Identity.read(self.process.pid)
        self.messages = queue.Queue(); self.records = [self.parent]
        def collect():
            for line in self.process.stdout:
                try: self.messages.put(json.loads(line))
                except ValueError: self.messages.put({'invalidProtocol': True})
        self.reader = threading.Thread(target=collect, daemon=True); self.reader.start()
        try:
            if host: self.root = Identity.read(self.until(lambda m: 'fixtureRootPID' in m)['fixtureRootPID'])
            else: self.root = self.parent
            self.records.append(self.root)
            self.send('init', 'initialize')
            self.until(lambda m: m.get('notification') == 'ready')
            self.send('busy', 'submit_text', {'text': 'controlled blocking model'})
            self.wait(lambda: (self.directory/'entered').exists())
            self.records.extend(Identity.read(p.pid) for p in self.root.process().children(recursive=True))
            guardians = [p for p in self.root.process().children() if 'maltose.runtime.lifetime' in p.cmdline()]
            if len(guardians) != 1: raise AssertionError('Expected exactly one native lifetime guardian')
            self.guardian = Identity.read(guardians[0].pid)
            if os.getpgid(self.guardian.pid) == self.root.pid: raise AssertionError('Guardian must survive root-group failure')
            if worker:
                self.worker = Identity.read(int((self.directory/'worker-pid').read_text()))
                if os.getpgid(self.worker.pid) == self.root.pid: raise AssertionError('Fixture must exercise an independent child group')
        except BaseException:
            self.close(); raise

    def send(self, identifier, method, params=None):
        self.process.stdin.write(json.dumps(dict(schemaVersion=1, requestID=identifier, method=method, params=params or {}))+'\n')
        self.process.stdin.flush()

    def until(self, predicate):
        deadline = time.monotonic()+10
        while time.monotonic()<deadline:
            message = self.messages.get(timeout=max(.01,deadline-time.monotonic()))
            if message.get('invalidProtocol'): raise AssertionError('Non-protocol output on native stdout')
            if predicate(message): return message
        raise TimeoutError('Fixture did not reach expected state')

    @staticmethod
    def wait(predicate, timeout=8):
        deadline=time.monotonic()+timeout
        while not predicate():
            if time.monotonic()>=deadline: raise TimeoutError('Owned process cleanup did not finish')
            time.sleep(.025)

    def assert_clean(self, case):
        self.wait(lambda: all(record.process() is None for record in self.records))
        case.assertFalse((self.directory/'late-write').exists())
        with RuntimeLease(self.directory): pass

    def close(self):
        for record in self.records:
            process=record.process()
            if process is not None: process.kill()
        self.process.wait(timeout=3)
        if not self.process.stdin.closed: self.process.stdin.close()
        self.reader.join(timeout=3); self.process.stdout.close(); self.log.close()


class NativeLifetimeTests(unittest.TestCase):
    def test_shutdown_signal_during_final_cleanup_preserves_guardian_acknowledgement(self):
        with tempfile.TemporaryDirectory() as directory:
            base = Path(directory)
            program = '''import sys,time
from pathlib import Path
from maltose.runtime.lifetime import NativeRuntimeLifetime
base=Path(sys.argv[1])
original=NativeRuntimeLifetime._request
def delayed(self,method,**params):
 if method=='finish':
  (base/'finishing').touch()
  time.sleep(.3)
 return original(self,method,**params)
NativeRuntimeLifetime._request=delayed
sys.argv=['maltose','--native-text-only','--brain','echo','--config',str(base/'none.toml')]
from maltose.desktop import main
main()
'''
            process = subprocess.Popen([sys.executable, '-c', program, directory], stdin=subprocess.PIPE,
                stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, cwd=directory,
                env={**os.environ, 'PYTHONPATH': str(Path(__file__).resolve().parents[1])})
            try:
                for identifier, method in [('init', 'initialize'), ('stop', 'shutdown')]:
                    process.stdin.write(json.dumps(dict(schemaVersion=1, requestID=identifier, method=method, params={}))+'\n')
                process.stdin.flush()
                BusyRuntime.wait(lambda: (base/'finishing').exists())
                process.send_signal(signal.SIGTERM)
                output, diagnostics = process.communicate(timeout=8)
                self.assertEqual(process.returncode, 0, diagnostics)
                self.assertNotIn('native_lifetime_final_cleanup_unconfirmed', diagnostics)
                self.assertTrue(any(json.loads(line).get('requestID') == 'stop' for line in output.splitlines()))
                with RuntimeLease(base): pass
            finally:
                if process.poll() is None: process.kill()
                process.communicate(timeout=3)

    def test_owner_eof_interrupts_busy_model_cleans_detached_worker_and_releases_lease(self):
        with tempfile.TemporaryDirectory() as directory:
            fixture=BusyRuntime(directory)
            unrelated=subprocess.Popen([sys.executable,'-c','import time;time.sleep(60)'])
            try:
                fixture.process.stdin.close()
                fixture.assert_clean(self)
                self.assertIsNone(unrelated.poll(),'Cleanup must not signal unrelated user processes')
                requests=''.join(json.dumps(dict(schemaVersion=1,requestID=name,method=method))+'\n'
                    for name,method in [('restart','initialize'),('stop','shutdown')])
                restarted=subprocess.run([sys.executable,'-m','maltose.desktop','--native-text-only','--brain','echo',
                    '--config',str(Path(directory)/'none.toml')],input=requests,text=True,capture_output=True,
                    cwd=directory,env={**os.environ,'PYTHONPATH':str(Path(__file__).resolve().parents[1])},timeout=8)
                self.assertEqual(restarted.returncode,0,restarted.stderr)
                replies=[json.loads(line) for line in restarted.stdout.splitlines()]
                self.assertTrue(any(reply.get('requestID')=='restart' and reply.get('ok') for reply in replies))
                self.assertFalse((Path(directory)/'late-write').exists(),'Restart must not replay the interrupted model')
            finally:
                fixture.close(); unrelated.kill(); unrelated.wait(timeout=3)

    def test_owner_host_crash_stops_busy_runtime_even_if_stdin_is_still_open(self):
        with tempfile.TemporaryDirectory() as directory:
            fixture=BusyRuntime(directory,host=True)
            try:
                fixture.process.kill(); fixture.process.wait(timeout=3)
                self.assertFalse(fixture.process.stdin.closed,'The guardian must independently observe host identity')
                fixture.assert_clean(self)
            finally: fixture.close()

    def test_native_root_group_crash_cleans_worker_in_another_group(self):
        with tempfile.TemporaryDirectory() as directory:
            fixture=BusyRuntime(directory)
            try:
                os.killpg(fixture.root.pid,signal.SIGKILL)
                fixture.assert_clean(self)
            finally: fixture.close()

    def test_unexpected_guardian_loss_cannot_leave_main_running_unprotected(self):
        with tempfile.TemporaryDirectory() as directory:
            fixture=BusyRuntime(directory,worker=False)
            try:
                fixture.guardian.process().kill()
                fixture.assert_clean(self)
                self.assertEqual(fixture.process.wait(timeout=3),70,
                    "Guardian failure must be visible as a failed runtime, not a successful shutdown")
            finally: fixture.close()


if __name__=='__main__': unittest.main()
