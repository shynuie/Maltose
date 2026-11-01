from contextlib import contextmanager
from datetime import datetime, timedelta, timezone
import io
import json
from pathlib import Path
import tempfile
import subprocess
import sys
import threading
import time
from types import SimpleNamespace
import unittest

from maltose.agent.agent import ControlledSpeaker, VoiceAgent
from maltose.agent.config import AgentConfig
from maltose.agent.brain import TurnContext
from maltose.agent.taskbrain import TaskBrain, ToolRegistry, MemoryStore
from maltose.agent.tasks import TaskManager, TaskStore, TaskStatus, FunctionTaskWorker
from maltose.runtime import EventHub
from maltose.runtime.control import AutonomyControl, AutonomyPaused
from maltose.runtime.ownership import RuntimeLease
from maltose.ui.native import NativeRuntimeBridge
from maltose.voice import ListeningEvent, STTResult, Utterance, SpeakerResult


def wait_until(predicate, seconds=3):
    deadline = time.monotonic() + seconds
    while not predicate():
        if time.monotonic() > deadline: raise AssertionError('Control condition timed out')
        time.sleep(0.005)


class AutonomyControlTests(unittest.TestCase):
    @contextmanager
    def manager(self, control, max_workers=1):
        with tempfile.TemporaryDirectory() as temporary:
            store = TaskStore(Path(temporary) / 'tasks.sqlite')
            manager = TaskManager(store, control_gate=control, max_workers=max_workers)
            try: yield manager
            finally: manager.shutdown(); store.close()

    def test_pause_closes_admission_and_returns_before_inflight_tool_finishes(self):
        events = []; control = AutonomyControl(lambda _, value: events.append(value))
        registry = ToolRegistry(); registry.control_gate = control
        entered = threading.Event(); release = threading.Event(); writes = []
        def write(_):
            entered.set(); release.wait(3); writes.append('completed')
        registry.register('write', '', {}, write)
        worker = threading.Thread(target=lambda: registry.execute('write', {})); worker.start()
        try:
            self.assertTrue(entered.wait(1))
            started = time.monotonic(); paused = control.pause('codex-task')
            self.assertLess(time.monotonic() - started, 0.2)
            self.assertEqual(paused['state'], 'pausing')
            with self.assertRaises(AutonomyPaused): registry.execute('write', {})
            with self.assertRaises(RuntimeError): control.resume('codex-task', paused['leaseID'], intent_confirmed=True)
            release.set(); worker.join(1)
            self.assertEqual(control.snapshot()['state'], 'paused')
            self.assertEqual(writes, ['completed'])
            with self.assertRaises(PermissionError): control.resume('other-task', paused['leaseID'], intent_confirmed=True)
            with self.assertRaises(PermissionError): control.resume('codex-task', paused['leaseID'])
            old_epoch = 0
            control.resume('codex-task', paused['leaseID'], intent_confirmed=True)
            with self.assertRaises(AutonomyPaused):
                with control.activity('stale-worker', expected_epoch=old_epoch): self.fail('Must not run')
            self.assertEqual([event['state'] for event in events], ['pausing', 'paused', 'active'])
        finally: release.set(); worker.join(1)

    def test_inflight_speech_blocks_handoff_and_new_speech_is_not_started(self):
        entered = threading.Event(); release = threading.Event(); calls = []
        provider = SimpleNamespace(synthesize=lambda _: (entered.set(), release.wait(3), calls.append('spoken')))
        control = AutonomyControl(); speaker = ControlledSpeaker(provider, control)
        worker = threading.Thread(target=lambda: speaker.synthesize('first')); worker.start()
        try:
            self.assertTrue(entered.wait(1)); state = control.pause('codex')
            self.assertEqual(state['activities'], {'speech': 1})
            with self.assertRaises(AutonomyPaused): speaker.synthesize('second')
            release.set(); worker.join(1)
            self.assertEqual(control.snapshot()['state'], 'paused'); self.assertEqual(calls, ['spoken'])
        finally: release.set(); worker.join(1)

    def test_tool_results_survive_handoff_and_unconfirmed_calls_do_not_execute(self):
        control = AutonomyControl(); calls = []; model_requests = []
        class Model:
            def complete(self, messages, _tools):
                model_requests.append(messages)
                return {'choices': [{'message': {'tool_calls': [
                    {'id': 'first', 'function': {'name': 'first', 'arguments': '{}'}},
                    {'id': 'second', 'function': {'name': 'second', 'arguments': '{}'}}]}}]}
        tools = ToolRegistry()
        def first(_): calls.append('first'); control.pause('codex'); return {'saved': True}
        tools.register('first', '', {}, first); tools.register('second', '', {}, lambda _: calls.append('second'))
        with tempfile.TemporaryDirectory() as temporary:
            brain = TaskBrain(Model(), memory=MemoryStore(Path(temporary) / 'memory.json'), tools=tools, control_gate=control)
            with self.assertRaises(AutonomyPaused): brain.process('fixture task')
            self.assertEqual(calls, ['first']); self.assertEqual(len(model_requests), 1)
            results = {message['tool_call_id']: json.loads(message['content']) for message in brain._session_messages if message['role'] == 'tool'}
            self.assertEqual(results['first'], {'saved': True})
            self.assertEqual(results['second']['execution'], 'unconfirmed')
            self.assertEqual(control.snapshot()['state'], 'paused')

    def test_stream_pause_closes_generator_and_cannot_continue_new_model_work(self):
        control = AutonomyControl(); yielded = threading.Event(); release = threading.Event(); closed = threading.Event()
        class Model:
            def stream(self, *_):
                try:
                    yield {'choices': [{'delta': {'content': 'first'}}]}
                    yielded.set(); release.wait(3)
                    yield {'choices': [{'delta': {'content': 'must not be emitted'}}]}
                finally: closed.set()
        with tempfile.TemporaryDirectory() as temporary:
            brain = TaskBrain(Model(), memory=MemoryStore(Path(temporary) / 'memory.json'), control_gate=control)
            chunks = []; errors = []
            def consume():
                try: chunks.extend(brain.process_stream('fixture'))
                except AutonomyPaused: errors.append('paused')
            thread = threading.Thread(target=consume); thread.start()
            try:
                self.assertTrue(yielded.wait(1)); control.pause('codex')
                self.assertEqual(control.snapshot()['state'], 'pausing')
                release.set(); thread.join(1)
                self.assertEqual(chunks, ['first']); self.assertEqual(errors, ['paused'])
                self.assertTrue(closed.is_set()); self.assertEqual(control.snapshot()['state'], 'paused')
            finally: release.set(); thread.join(1)

    def test_background_queue_does_not_cross_pause_or_resume_without_new_intent(self):
        control = AutonomyControl(); release = threading.Event(); entered = threading.Event(); calls = []
        with self.manager(control) as manager:
            def work(data):
                calls.append(data['name'])
                if data['name'] == 'first': entered.set(); release.wait(3)
                return data['name']
            manager.register_worker('local', FunctionTaskWorker(work))
            tasks = manager.create_plan([{'title': name, 'worker_type': 'local', 'input': {'name': name}} for name in ['first', 'second']])
            try:
                self.assertTrue(entered.wait(1)); paused = control.pause('codex')
                self.assertEqual(paused['state'], 'pausing')
                release.set(); wait_until(lambda: control.snapshot()['state'] == 'paused')
                control.resume('codex', paused['leaseID'], intent_confirmed=True, before_resume=manager.store.hold_deferred_work)
                wait_until(lambda: manager.get_status(tasks[1].id)['status'] == TaskStatus.HELD)
                self.assertEqual(calls, ['first'])
                manager.retry(tasks[1].id)
                wait_until(lambda: manager.get_status(tasks[1].id)['status'] == TaskStatus.SUCCEEDED)
                self.assertEqual(calls, ['first', 'second'])
            finally: release.set()

    def test_scheduled_work_is_held_until_explicit_revalidation_after_resume(self):
        control = AutonomyControl(); ran = threading.Event()
        with self.manager(control) as manager:
            manager.register_worker('local', FunctionTaskWorker(lambda _: ran.set() or 'done'))
            scheduled = manager.create_schedule('fixture', 'local', (datetime.now(timezone.utc) + timedelta(seconds=.1)).isoformat())
            paused = control.pause('codex')
            control.resume('codex', paused['leaseID'], intent_confirmed=True, before_resume=manager.store.hold_deferred_work)
            self.assertEqual(manager.store.get_schedule(scheduled['schedule_id']).status, 'held')
            self.assertFalse(ran.wait(.65))
            manager.resume_schedule(scheduled['schedule_id'])
            self.assertTrue(ran.wait(2))

    def test_recovered_paused_runtime_holds_legacy_work_but_normal_start_keeps_schedules(self):
        for paused in (True, False):
            control = AutonomyControl()
            if paused: control.pause('restored-codex-task')
            with tempfile.TemporaryDirectory() as temporary:
                store = TaskStore(Path(temporary) / 'tasks.sqlite')
                record = store.create_schedule('legacy', 'local', (datetime.now(timezone.utc) + timedelta(hours=1)).isoformat())
                manager = TaskManager(store, control_gate=control)
                try: self.assertEqual(store.get_schedule(record.id).status, 'held' if paused else 'active')
                finally: manager.shutdown(); store.close()

    def test_pause_rpc_does_not_block_panel_reply_needed_by_admitted_tool(self):
        output = io.StringIO(); bridge = NativeRuntimeBridge(EventHub(), output_stream=output)
        self.addCleanup(bridge.close)
        def call(identity, method, params=None):
            bridge.receive_line(json.dumps(dict(schemaVersion=1, requestID=identity, method=method, params=params or {})))
            return next(message for message in reversed([json.loads(line) for line in output.getvalue().splitlines()]) if message.get('requestID') == identity)
        call('init', 'initialize')
        result = []; errors = []
        def worker():
            try:
                with bridge.control.activity('tool'): result.append(bridge.call_panel({'get_user_view': {}}, timeout=2))
            except BaseException as error: errors.append(error)
        thread = threading.Thread(target=worker); thread.start()
        try:
            wait_until(lambda: 'serverRequestID' in output.getvalue())
            request = next(json.loads(line) for line in output.getvalue().splitlines() if 'serverRequestID' in line)
            response = call('pause', 'pause_autonomy', {'ownerID': 'codex'})
            self.assertEqual(response['result']['state'], 'pausing')
            bridge.receive_line(json.dumps(dict(schemaVersion=1, sessionID=bridge.session_id,
                replyTo=request['serverRequestID'], ok=True, result={'ok': True, 'view': {}})))
            thread.join(1)
            self.assertFalse(errors); self.assertEqual(len(result), 1)
            self.assertEqual(bridge.control.snapshot()['state'], 'paused')
        finally: thread.join(2)

    def test_routed_inputs_preserve_source_identity_and_stale_messages_are_deferred(self):
        bridge = NativeRuntimeBridge(EventHub(), output_stream=io.StringIO()); self.addCleanup(bridge.close)
        events = []; bridge.hub.publish = lambda kind, payload: events.append((kind, payload))
        context = TurnContext(user_id=None, speaker_status='unknown')
        self.assertFalse(bridge.route_input('ordinary input', context, 'voice', 0, 'one'))
        bridge.routing_enabled = True
        self.assertTrue(bridge.route_input('@codex fixture', context, 'native', 0, 'two'))
        bridge.control.pause('codex')
        self.assertTrue(bridge.route_input('old input', context, 'native', 0, 'three'))
        self.assertTrue(bridge.route_input('new voice', context, 'voice', bridge.control.epoch, 'four'))
        inputs = [value for kind, value in events if kind == 'input_routed']
        self.assertEqual([value['messageID'] for value in inputs], ['two', 'three', 'four'])
        self.assertTrue(inputs[1]['deferred']); self.assertFalse(inputs[2]['deferred'])
        self.assertEqual(inputs[2]['speaker'], {'userID': None, 'status': 'unknown', 'score': None})

    def test_new_turn_does_not_reuse_previous_verified_identity_history(self):
        prompts = []
        class Model:
            def complete(self, messages, _):
                prompts.append(messages)
                return {'choices': [{'message': {'content': 'fixture answer'}}]}
        with tempfile.TemporaryDirectory() as temporary:
            brain = TaskBrain(Model(), memory=MemoryStore(Path(temporary) / 'memory.json'))
            brain.process('verified private fixture', TurnContext(user_id='fixture-user', speaker_status='identified'))
            brain.process('unverified input', TurnContext(user_id='fixture-user', speaker_status='unknown'))
            self.assertNotIn('verified private fixture', json.dumps(prompts[-1]))

    def test_actual_voice_loop_routes_paused_speech_and_does_not_send_wake_word_to_codex(self):
        control = AutonomyControl(); control.pause('codex')
        transcripts = iter(['麥芽糖', '新增開發需求'])
        stt = SimpleNamespace(transcribe=lambda _: STTResult(text=next(transcripts), language='zh', duration=.01, segments=[]))
        calls = []; routed = []; observed = []
        brain = SimpleNamespace(process=lambda *_args, **_kwargs: calls.append('brain'), begin_session=lambda: calls.append('reset-main-session'))
        speaker = SimpleNamespace(synthesize=lambda _: calls.append('speech'))
        utterance = Utterance(pcm=b'\0' * 320, sample_rate=16000, sample_width=2, channels=1)
        def listener(*_args, **_kwargs):
            yield ListeningEvent(kind='wake_detected', keyword='麥芽糖')
            yield ListeningEvent(kind='speech_ended', utterance=utterance)
        def route(text, context, source, epoch, identity):
            routed.append((text, context, source, epoch, identity)); agent.request_shutdown(); return True
        with tempfile.TemporaryDirectory() as temporary:
            agent = VoiceAgent(config=AgentConfig(output_dir=Path(temporary), wake_word_detector=object()), brain=brain, transcriber=stt, speaker=speaker,
                speaker_identifier=SimpleNamespace(identify=lambda _: SpeakerResult('fixture', .4, 'unknown')),
                listener_factory=listener, control_gate=control, input_router=route)
            agent.voice_context_observer = observed.append
            agent.run()
        self.assertEqual(len(routed), 1); self.assertEqual(routed[0][0], '新增開發需求')
        self.assertEqual(routed[0][1].speaker_status, 'unknown'); self.assertEqual(routed[0][2], 'voice')
        self.assertTrue(routed[0][4]); self.assertEqual(calls, [])
        self.assertEqual(len(observed), 2, 'Wake-only speech still updates the verification scope')

    def test_actual_text_loop_finalizes_partial_stream_when_handoff_interrupts_model(self):
        control = AutonomyControl(); first = threading.Event(); release = threading.Event(); closed = threading.Event()
        class Model:
            def stream(self, *_):
                try:
                    yield {'choices': [{'delta': {'content': 'partial fixture'}}]}
                    release.wait(3)
                    yield {'choices': [{'delta': {'content': 'must not appear'}}]}
                finally: closed.set()
        hub = EventHub(); events = []
        def publish(kind, payload):
            events.append((kind, payload))
            if kind == 'assistant_delta': first.set()
        hub.publish = publish
        with tempfile.TemporaryDirectory() as temporary:
            brain = TaskBrain(Model(), memory=MemoryStore(Path(temporary) / 'memory.json'), control_gate=control)
            agent = VoiceAgent(brain=brain, event_hub=hub, voice_enabled=False, control_gate=control)
            thread = threading.Thread(target=agent.run); thread.start()
            try:
                agent.submit_text('main fixture task', source='native')
                self.assertTrue(first.wait(1)); control.pause('codex')
                self.assertEqual(control.snapshot()['state'], 'pausing')
                release.set(); wait_until(lambda: control.snapshot()['state'] == 'paused')
                wait_until(lambda: any(kind == 'assistant_end' for kind, _ in events))
                final = next(payload for kind, payload in events if kind == 'assistant_end')
                self.assertEqual(final['content'], 'partial fixture'); self.assertTrue(final['interrupted'])
                self.assertTrue(closed.is_set()); self.assertIsNone(agent._assistant_stream_id)
            finally: release.set(); agent.request_shutdown(); thread.join(2)
            self.assertFalse(thread.is_alive())

    def test_native_lease_covers_worker_drain_after_main_function_returns(self):
        program = '''
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
import time
from maltose.agent import cli
def fixture_main(*, native_owner_lost=None, native_control_ready=None):
    assert callable(native_owner_lost) and callable(native_control_ready)
    executor=ThreadPoolExecutor(max_workers=1)
    def worker():
        while not Path('release').exists(): time.sleep(.01)
    executor.submit(worker)
    Path('main-returned').touch()
cli.main=fixture_main
from maltose.desktop import main
main()
'''
        with tempfile.TemporaryDirectory() as temporary:
            directory = Path(temporary)
            # Use the same installed package as the native process; no model or microphone.
            child = subprocess.Popen([sys.executable, '-c', program, '--config', str(directory / 'none.toml')],
                                     cwd=directory, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
            try:
                wait_until(lambda: (directory / 'main-returned').exists())
                self.assertIsNone(child.poll())
                with self.assertRaises(RuntimeError): RuntimeLease(directory)
                (directory / 'release').touch(); self.assertEqual(child.wait(timeout=3), 0)
                with RuntimeLease(directory): pass
            finally:
                (directory / 'release').touch()
                if child.poll() is None: child.kill()
                child.wait(timeout=3)


if __name__ == '__main__': unittest.main()
