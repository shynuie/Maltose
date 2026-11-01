from __future__ import annotations
import io
import json
import os
from pathlib import Path
import queue
import subprocess
import sys
import tempfile
import threading
import time
import unittest
from types import SimpleNamespace

from maltose.runtime import EventHub
from maltose.ui.native import NativeRuntimeBridge


class NativeProtocolTests(unittest.TestCase):
    def test_graceful_shutdown_eof_keeps_final_events_until_main_cleanup(self):
        output = io.StringIO()
        source = io.StringIO('\n'.join(json.dumps(request) for request in [
            {'schemaVersion': 1, 'requestID': 'init', 'method': 'initialize'},
            {'schemaVersion': 1, 'requestID': 'stop', 'method': 'shutdown'},
        ]) + '\n')
        hub = EventHub()
        bridge = NativeRuntimeBridge(hub, input_stream=source, output_stream=output)
        bridge.attach(SimpleNamespace(request_shutdown=lambda: None), None)
        bridge.start()
        bridge._threads[0].join(timeout=2)
        self.assertFalse(bridge._threads[0].is_alive())
        self.assertFalse(bridge._closed.is_set(), 'Explicit shutdown must leave the event channel open until Agent cleanup')
        hub.publish('audio_input_state', {'active': False, 'streams': 0})
        hub.publish('state_changed', {'state': 'shutdown'})
        bridge.close()
        events = [json.loads(line).get('event') for line in output.getvalue().splitlines() if json.loads(line).get('event')]
        self.assertTrue(any(event['type'] == 'audio_input_state' and not event['payload']['active'] for event in events))
        self.assertEqual(events[-1]['payload']['state'], 'shutdown')

    def test_native_approval_action_is_explicit_scoped_and_deduplicated(self):
        output = io.StringIO()
        bridge = NativeRuntimeBridge(EventHub(), output_stream=output)
        self.addCleanup(bridge.close)
        calls = []
        bridge.action_handler = lambda action, value: calls.append((action, value))
        def call(request):
            bridge.receive_line(json.dumps(request))
            return json.loads(output.getvalue().splitlines()[-1])
        call({'schemaVersion': 1, 'requestID': 'init', 'method': 'initialize'})
        request = {'schemaVersion': 1, 'requestID': 'approve', 'method': 'ui_action',
                   'params': {'actionID': 'filesystem.approve', 'value': {'approval_id': 'record-1'}}}
        self.assertTrue(call(request)['ok'])
        self.assertTrue(call(request)['ok'])
        self.assertEqual(calls, [('filesystem.approve', {'approval_id': 'record-1'})])
        self.assertFalse(call({**request, 'requestID': 'bad', 'params': {'actionID': 'run_command', 'value': {}}})['ok'])
        def denied(*_): raise PermissionError('Approval expired')
        bridge.action_handler = denied
        self.assertFalse(call({**request, 'requestID': 'expired'})['ok'])
        self.assertTrue(call({'schemaVersion': 1, 'requestID': 'still-connected', 'method': 'snapshot'})['ok'])

    def test_handshake_validation_and_dedup_prevent_repeated_input(self):
        output = io.StringIO()
        hub = EventHub()
        bridge = NativeRuntimeBridge(hub, output_stream=output)
        received = []
        agent = SimpleNamespace(state=SimpleNamespace(value='standby'), submit_text=lambda text, **_: received.append(text),
                                request_shutdown=lambda: None)
        bridge.attach(agent, None)
        bridge._ready = True
        def call(request):
            bridge.receive_line(json.dumps(request))
            return json.loads(output.getvalue().splitlines()[-1])
        try:
            request = {'schemaVersion': 1, 'requestID': 'input', 'method': 'submit_text', 'params': {'text': 'hello'}}
            self.assertFalse(call(request)['ok'])
            initialized = call({'schemaVersion': 1, 'requestID': 'init', 'method': 'initialize'})
            self.assertTrue(initialized['ok'])
            self.assertEqual(initialized['result']['product'], 'Maltose')
            self.assertTrue(call(request)['ok'])
            self.assertTrue(call(request)['ok'])
            self.assertEqual(received, ['hello'])
            self.assertFalse(call({**request, 'params': {'text': 'different'}})['ok'])
            self.assertEqual(received, ['hello'])
            self.assertFalse(call({'schemaVersion': 99, 'requestID': 'wrong', 'method': 'shutdown'})['ok'])
        finally:
            bridge.close()

    def test_malformed_input_produces_error_without_ending_connection(self):
        output = io.StringIO()
        bridge = NativeRuntimeBridge(EventHub(), output_stream=output)
        try:
            for line in ['bad json', '[]', '{"schemaVersion":1,"method":"shutdown"}']:
                bridge.receive_line(line)
                self.assertFalse(json.loads(output.getvalue().splitlines()[-1])['ok'])
            bridge.receive_line('{"schemaVersion":1,"requestID":"ok","method":"initialize"}')
            self.assertTrue(json.loads(output.getvalue().splitlines()[-1])['ok'])
        finally:
            bridge.close()


class NativeRuntimeProcessTests(unittest.TestCase):
    def test_native_library_stdout_cannot_corrupt_app_protocol(self):
        with tempfile.TemporaryDirectory() as directory:
            program = '''import os,sys
from maltose.agent import cli
from maltose.desktop import main
original=cli.VoiceAgent
class LoudAgent(original):
 def __init__(self,*args,**kwargs):
  os.write(1,b'native library diagnostic output\\n');super().__init__(*args,**kwargs)
cli.VoiceAgent=LoudAgent
sys.argv=['maltose','--native-text-only','--brain','echo','--speaker-recognition','none','--config',sys.argv[1]]
main()
'''
            requests = '\n'.join(json.dumps({'schemaVersion':1,'requestID':name,'method':method}) for name,method in [('init','initialize'),('stop','shutdown')])+'\n'
            child = subprocess.run([sys.executable,'-c',program,str(Path(directory)/'none.toml')],input=requests,
                cwd=directory,text=True,capture_output=True,timeout=15)
            self.assertEqual(child.returncode,0,child.stderr)
            messages = [json.loads(line) for line in child.stdout.splitlines()]
            self.assertTrue(any(message.get('requestID')=='init' and message['ok'] for message in messages))
            self.assertIn('native library diagnostic output',child.stderr)

    def test_existing_voice_agent_runs_text_only_over_stdio_and_exits_cleanly(self):
        with tempfile.TemporaryDirectory() as directory:
            log_path = Path(directory) / 'runtime.log'
            messages = queue.Queue()
            with log_path.open('w') as log:
                child = subprocess.Popen([sys.executable, '-m', 'maltose.desktop', '--native-text-only',
                                          '--brain', 'echo', '--config', str(Path(directory) / 'none.toml')],
                                         stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=log,
                                         text=True, cwd=directory, env=os.environ.copy())
                def collect():
                    for line in child.stdout:
                        try: messages.put(json.loads(line))
                        except ValueError: messages.put({'invalid': line})
                thread = threading.Thread(target=collect, daemon=True)
                thread.start()
                def send(request_id, method, **params):
                    child.stdin.write(json.dumps({'schemaVersion': 1, 'requestID': request_id,
                                                  'method': method, 'params': params}) + '\n')
                    child.stdin.flush()
                def until(predicate):
                    deadline = time.monotonic() + 15
                    seen = []
                    while time.monotonic() < deadline:
                        item = messages.get(timeout=max(.1, deadline-time.monotonic()))
                        self.assertNotIn('invalid', item, 'stdout must contain only protocol JSON')
                        seen.append(item)
                        if predicate(item): return item, seen
                    self.fail('Runtime response timed out')
                try:
                    send('init', 'initialize')
                    response, _ = until(lambda m: m.get('requestID') == 'init')
                    self.assertTrue(response['ok'])
                    self.assertEqual(response['result']['pid'], child.pid)
                    self.assertEqual(response['result']['processGroupID'], child.pid)
                    _, ready_events = until(lambda m: m.get('notification') == 'ready')
                    send('no-approval-service', 'ui_action', actionID='filesystem.approve', value={'approval_id': 'not-present'})
                    denied, _ = until(lambda m: m.get('requestID') == 'no-approval-service')
                    self.assertFalse(denied['ok'], 'Disabled approval services must not acknowledge a decision as applied')
                    send('text', 'submit_text', text='native test')
                    answer, seen = until(lambda m: m.get('event', {}).get('type') == 'assistant_message')
                    self.assertIn('native test', answer['event']['payload']['content'])
                    self.assertEqual(sum(m.get('event', {}).get('type') == 'user_message' for m in seen), 1)
                    user = next(m['event'] for m in seen if m.get('event', {}).get('type') == 'user_message')
                    self.assertEqual(user['payload']['source'], 'native')
                    self.assertTrue(any(m.get('requestID') == 'text' and m['ok'] for m in seen))
                    send('exit', 'shutdown')
                    self.assertEqual(child.wait(timeout=5), 0)
                    self.assertNotIn('stt_warmup_started', log_path.read_text())
                finally:
                    if child.poll() is None:
                        child.kill(); child.wait(timeout=5)
                    child.stdin.close(); child.stdout.close(); thread.join(timeout=2)

    def test_owner_eof_stops_idle_agent(self):
        with tempfile.TemporaryDirectory() as directory:
            with open(os.devnull, 'w') as log:
                child = subprocess.Popen([sys.executable, '-m', 'maltose.desktop', '--native-text-only',
                                          '--brain', 'echo', '--config', str(Path(directory) / 'none.toml')],
                                         stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=log,
                                         text=True, cwd=directory)
                try:
                    child.stdin.close()
                    self.assertIsNotNone(child.wait(timeout=5))
                finally:
                    if child.poll() is None: child.kill(); child.wait(timeout=5)
                    child.stdout.close()
