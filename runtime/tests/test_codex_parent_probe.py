import importlib.util
import io
import json
from pathlib import Path
import subprocess
import sys
from types import SimpleNamespace
import unittest

import psutil

spec=importlib.util.spec_from_file_location('maltose_parent_probe',Path(__file__).resolve().parents[1]/'dev/tools/verify_codex_parent_crash.py')
probe=importlib.util.module_from_spec(spec)
spec.loader.exec_module(probe)


class CodexParentProbeTests(unittest.TestCase):
    def test_cleanup_checks_creation_identity_and_preserves_unrelated_process(self):
        first=subprocess.Popen([sys.executable,'-c','import time; time.sleep(30)'])
        unrelated=subprocess.Popen([sys.executable,'-c','import time; time.sleep(30)'])
        try:
            owned=probe.identity(psutil.Process(first.pid))
            probe.stop_owned([{**owned,'created':owned['created']+1}])
            self.assertIsNone(first.poll(),'A reused PID must never be treated as the recorded process')
            probe.stop_owned([owned])
            first.wait(timeout=3)
            self.assertFalse(probe.alive(owned))
            self.assertIsNone(unrelated.poll(),'Cleanup must not terminate other processes')
        finally:
            for child in (first,unrelated):
                if child.poll() is None: child.kill()
                child.wait(timeout=3)

    def test_rpc_preserves_notifications_before_response_and_never_retries(self):
        output=io.StringIO('\n'.join(json.dumps(value) for value in [
            dict(method='fixture/event',params={'state':'working'}),dict(id='probe-1',result=None)])+'\n')
        process=SimpleNamespace(stdout=output,stdin=io.StringIO())
        rpc=probe.RPC(process)
        self.assertIsNone(rpc.call('fixture/read',timeout=1))
        self.assertEqual([event['method'] for event in rpc.events],['fixture/event'])
        requests=[json.loads(line) for line in process.stdin.getvalue().splitlines()]
        self.assertEqual(len(requests),1)
        self.assertEqual(requests[0]['method'],'fixture/read')

    def test_probe_refuses_to_approve_human_requests(self):
        process=SimpleNamespace(stdout=io.StringIO(json.dumps(dict(id='approval',method='item/commandExecution/requestApproval',params={}))+'\n'),stdin=io.StringIO())
        rpc=probe.RPC(process)
        with self.assertRaisesRegex(RuntimeError,'human interaction'): rpc.next(1)
        response=json.loads(process.stdin.getvalue())
        self.assertEqual(response['id'],'approval')
        self.assertEqual(response['error']['code'],-32000)
        self.assertNotIn('result',response)
        self.assertEqual(rpc.interactions,['item/commandExecution/requestApproval'])


if __name__=='__main__': unittest.main()
