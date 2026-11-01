import io
import json
import os
from pathlib import Path
import tempfile
import subprocess
import threading
import time
from types import SimpleNamespace
import unittest
from unittest.mock import patch

from maltose.agent.brain import TurnContext
from maltose.agent.agent import VoiceAgent
from maltose.agent.taskbrain import TaskBrain, MemoryStore
from maltose.codex.native_service import NativeCollaborationService, CONTROL_OWNER
from maltose.codex.native_tools import NativeCodexToolAdapter
from maltose.runtime import EventHub
from maltose.ui.native import NativeRuntimeBridge


class NativeCollaborationTests(unittest.TestCase):
    def service(self, directory):
        root = Path(directory); (root / 'repository' / '.git').mkdir(parents=True)
        return NativeCollaborationService(root / 'config', root / 'repository')

    def test_outbox_survives_restart_and_only_explicit_ack_removes_exact_input(self):
        with tempfile.TemporaryDirectory() as directory:
            service = self.service(directory)
            payload = dict(messageID='stable-id', content='@codex fixture', source='voice', speaker={'status': 'identified', 'userID': 'owner'})
            service.save_input(payload); service.save_input(payload)
            with self.assertRaises(ValueError): service.save_input({**payload, 'content': 'conflict'})
            restored = NativeCollaborationService(Path(directory) / 'config', service.repository)
            self.assertEqual(restored.pending_inputs(), [payload])
            self.assertEqual(os.stat(restored._inputs_path).st_mode & 0o777, 0o600)
            restored.acknowledge('other-id'); self.assertEqual(restored.pending_inputs(), [payload])
            restored.acknowledge('stable-id')
            self.assertEqual(NativeCollaborationService(Path(directory) / 'config', service.repository).pending_inputs(), [])

    def test_outbox_rejects_unsafe_file_and_failed_write_does_not_claim_acceptance(self):
        with tempfile.TemporaryDirectory() as directory:
            service = self.service(directory)
            with patch('maltose.codex.workspaces.CodexWorkspaceManager._save', side_effect=OSError('fixture disk full')):
                with self.assertRaises(OSError): service.save_input({'messageID': 'not-saved'})
            self.assertEqual(service.pending_inputs(), [])
            service.save_input({'messageID': 'saved'})
            service._inputs_path.chmod(0o644)
            with self.assertRaises(PermissionError): NativeCollaborationService(Path(directory) / 'config', service.repository)
            service._inputs_path.chmod(0o600)
            original = service._inputs_path.with_suffix('.original'); service._inputs_path.rename(original)
            service._inputs_path.symlink_to(original)
            with self.assertRaises(OSError): NativeCollaborationService(Path(directory) / 'config', service.repository)

    def test_verified_delegation_persists_before_pause_and_waits_for_actual_tool_drain(self):
        with tempfile.TemporaryDirectory() as directory:
            service = self.service(directory); hub = EventHub()
            bridge = NativeRuntimeBridge(hub, output_stream=io.StringIO(), collaboration=service)
            self.addCleanup(bridge.close)
            brain = SimpleNamespace(_identity_is_known=lambda: True, _active_user_id='owner')
            bridge.brain = brain; bridge.routing_enabled = True; bridge.conversation_id = 'conversation'
            tool = NativeCodexToolAdapter(bridge).tools()[0]
            request = dict(objective='Implement fixture', constraints=['Preserve edits'], acceptanceCriteria=['Check passes'], context='Relevant project state')
            with bridge.control.activity('tool'):
                result = tool.handler(request)
                self.assertTrue(result['accepted']); self.assertFalse(result['executionCompleted'])
                self.assertEqual(bridge.control.snapshot()['state'], 'pausing')
                saved = service.pending_inputs()[0]
                self.assertEqual(saved['taskID'], result['taskID'])
                self.assertEqual(saved['delegation'], request)
                self.assertEqual(saved['speaker'], {'userID': 'owner', 'status': 'identified'})
                self.assertEqual(saved['author'], 'maltose')
            self.assertEqual(bridge.control.snapshot()['state'], 'paused')
            self.assertEqual(bridge.control.snapshot()['ownerID'], CONTROL_OWNER)
            # A crash before App acknowledgement must pause before model/scheduler startup.
            restored = NativeRuntimeBridge(EventHub(), output_stream=io.StringIO(), collaboration=NativeCollaborationService(Path(directory) / 'config', service.repository))
            self.addCleanup(restored.close)
            restored.receive_line(json.dumps(dict(schemaVersion=1, requestID='init', method='initialize', params={'inputRouting': True})))
            self.assertEqual(restored.control.snapshot()['state'], 'paused')

    def test_unknown_identity_or_failed_durable_save_never_starts_delegation(self):
        with tempfile.TemporaryDirectory() as directory:
            service = self.service(directory)
            bridge = NativeRuntimeBridge(EventHub(), output_stream=io.StringIO(), collaboration=service); self.addCleanup(bridge.close)
            bridge.routing_enabled = True
            bridge.brain = SimpleNamespace(_identity_is_known=lambda: False)
            tool = NativeCodexToolAdapter(bridge).tools()[0]
            request = dict(objective='Fixture', constraints=[], acceptanceCriteria=['Pass'])
            self.assertEqual(tool.handler(request)['error']['code'], 'identity_required')
            self.assertEqual(service.pending_inputs(), []); self.assertTrue(bridge.control.active)
            bridge.brain = SimpleNamespace(_identity_is_known=lambda: True, _active_user_id='owner')
            with patch.object(service, 'save_input', side_effect=OSError('fixture disk full')):
                with self.assertRaises(OSError): tool.handler(request)
            self.assertTrue(bridge.control.active)

    def test_only_current_native_human_context_can_delegate_without_speaker_identity(self):
        for source in ('native', 'voice', 'web', None):
            with self.subTest(source=source), tempfile.TemporaryDirectory() as directory:
                service=self.service(directory); bridge=NativeRuntimeBridge(EventHub(),output_stream=io.StringIO(),collaboration=service)
                self.addCleanup(bridge.close); bridge.routing_enabled=True; bridge.conversation_id='conversation'
                class Model:
                    def __init__(self): self.calls=0
                    def complete(inner,_messages,_tools):
                        inner.calls+=1
                        if inner.calls>1: return {'choices':[{'message':{'content':'拒絕未驗證的語音／遠端輸入'}}]}
                        return {'choices':[{'message':{'tool_calls':[dict(id='delegate',type='function',function=dict(name='delegate_to_codex',
                            arguments=json.dumps(dict(objective='Fixture development',constraints=[],acceptanceCriteria=['Pass fixture']))))]}}]}
                brain=TaskBrain(Model(),memory=MemoryStore(Path(directory)/'memory.json'),control_gate=bridge.control)
                bridge.brain=brain
                from maltose.agent.capabilities import register_capability_adapter
                from maltose.runtime.control import AutonomyPaused
                register_capability_adapter(brain.tools,NativeCodexToolAdapter(bridge))
                context=TurnContext(speaker_status='unknown',input_source=source)
                if source=='native':
                    with self.assertRaises(AutonomyPaused): brain.process('委派開發',context)
                    saved=service.pending_inputs()[0]
                    self.assertEqual(saved['inputSource'],'native')
                    self.assertEqual(saved['speaker'],dict(userID=None,status='unknown'))
                    self.assertFalse(brain._identity_is_known())
                else:
                    brain.process('委派開發',context)
                    self.assertEqual(service.pending_inputs(),[]); self.assertTrue(bridge.control.active)

    def test_unacknowledged_delegation_blocks_resume_until_controller_persists_handoff(self):
        with tempfile.TemporaryDirectory() as directory:
            service = self.service(directory)
            bridge = NativeRuntimeBridge(EventHub(), output_stream=io.StringIO(), collaboration=service)
            self.addCleanup(bridge.close)
            bridge.receive_line(json.dumps(dict(schemaVersion=1, requestID='init', method='initialize')))
            bridge.agent = SimpleNamespace(state=SimpleNamespace(value='standby')); bridge._ready = True
            lease = bridge.control.pause(CONTROL_OWNER)
            params = dict(ownerID=CONTROL_OWNER, leaseID=lease['leaseID'], intentConfirmed=True)
            service.save_input(dict(messageID='pending-delegation', kind='codex_delegation'))
            with self.assertRaisesRegex(RuntimeError, 'durably acknowledged'):
                bridge._dispatch('resume_autonomy', params)
            self.assertEqual(bridge.control.snapshot()['state'], 'paused')
            self.assertEqual(len(service.pending_inputs()), 1)
            bridge._dispatch('acknowledge_input', dict(messageID='pending-delegation'))
            result = bridge._dispatch('resume_autonomy', params)
            self.assertEqual(result['state'], 'active')

    def test_routed_voice_reenters_actual_brain_with_runtime_identity_while_native_text_stays_unknown(self):
        with tempfile.TemporaryDirectory() as directory:
            service = self.service(directory); hub = EventHub(); contexts = []; identities = []; done = threading.Event()
            class Model:
                def complete(self, _messages, _tools):
                    identities.append(brain._identity_is_known())
                    if len(identities) == 2: done.set()
                    return {'choices': [{'message': {'content': 'fixture answer'}}]}
            class Brain(TaskBrain):
                def process_stream(self, text, context=None):
                    contexts.append(context)
                    yield from super().process_stream(text, context=context)
            bridge = NativeRuntimeBridge(hub, output_stream=io.StringIO(), collaboration=service); self.addCleanup(bridge.close)
            brain = Brain(Model(), memory=MemoryStore(Path(directory) / 'memory.json'), control_gate=bridge.control)
            agent = VoiceAgent(brain=brain, voice_enabled=False, event_hub=hub, control_gate=bridge.control)
            bridge.attach(agent, brain)
            bridge.receive_line(json.dumps(dict(schemaVersion=1, requestID='init', method='initialize', params={'inputRouting': True})))
            bridge._ready = True
            lease = bridge.control.pause(CONTROL_OWNER)
            owner = TurnContext(user_id='owner', speaker_status='identified', speaker_score=.9, input_source='voice')
            bridge.route_input('@maltose：新的方向', owner, 'voice', bridge.control.epoch, 'voice-input')
            bridge._dispatch('acknowledge_input', {'messageID': 'voice-input'})
            bridge._dispatch('resume_autonomy', dict(ownerID=CONTROL_OWNER, leaseID=lease['leaseID'], intentConfirmed=True))
            bridge._dispatch('submit_routed_voice', dict(messageID='voice-input', runtimeSessionID=bridge.session_id, text='新的方向'))
            bridge._dispatch('submit_text', dict(messageID='native-input', text='鍵盤輸入'))
            worker = threading.Thread(target=agent.run); worker.start()
            try:
                self.assertTrue(done.wait(3))
                self.assertEqual(identities, [True, False])
                self.assertEqual([(c.user_id, c.speaker_status, c.input_source) for c in contexts],
                    [('owner', 'identified', 'voice'), (None, 'unknown', 'native')])
                self.assertEqual(service.pending_inputs(), [])
            finally: agent.request_shutdown(); worker.join(3)
            self.assertFalse(worker.is_alive())

    def test_voice_replay_rejects_forgery_stale_session_changed_text_expired_proof_and_second_send(self):
        bridge = NativeRuntimeBridge(EventHub(), output_stream=io.StringIO()); self.addCleanup(bridge.close)
        queued = []
        bridge.agent = SimpleNamespace(submit_routed_voice=lambda text, **kw: queued.append((text, kw)))
        bridge.receive_line(json.dumps(dict(schemaVersion=1, requestID='init', method='initialize', params={'inputRouting': True})))
        bridge._ready = True
        owner = TurnContext(user_id='owner', speaker_status='identified')
        bridge.route_input('@maltose：fixture', owner, 'voice', 0, 'voice')
        params = dict(messageID='voice', runtimeSessionID=bridge.session_id, text='fixture')
        for invalid in [{**params, 'messageID': 'forged', 'speaker': {'userID': 'owner', 'status': 'identified'}},
                        {**params, 'runtimeSessionID': 'old-runtime'}, {**params, 'text': 'different'}]:
            with self.assertRaises(PermissionError): bridge._dispatch('submit_routed_voice', invalid)
        with patch('maltose.ui.native.time.monotonic', return_value=time.monotonic() + 121):
            with self.assertRaises(PermissionError): bridge._dispatch('submit_routed_voice', params)
        self.assertEqual(queued, [])
        bridge._dispatch('submit_routed_voice', params)
        with self.assertRaises(PermissionError): bridge._dispatch('submit_routed_voice', params)
        self.assertEqual(len(queued), 1)
        self.assertEqual(queued[0][1]['context_provider'](), owner)
        bridge.route_input('other voice', TurnContext(user_id='other', speaker_status='identified'), 'voice', 0, 'other')
        bridge.route_input('owner returns', owner, 'voice', 0, 'owner-again')
        self.assertIsNone(queued[0][1]['context_provider'](), 'An old proof must not revive when the same speaker returns')

    def test_queued_voice_is_deferred_without_model_work_after_verification_changes(self):
        hub = EventHub(); deferred = threading.Event(); calls = []
        bridge = NativeRuntimeBridge(hub, output_stream=io.StringIO()); self.addCleanup(bridge.close)
        brain = SimpleNamespace(process=lambda *a, **kw: calls.append(kw) or 'must not run')
        agent = VoiceAgent(brain=brain, voice_enabled=False, event_hub=hub, control_gate=bridge.control)
        bridge.attach(agent, brain)
        bridge.receive_line(json.dumps(dict(schemaVersion=1, requestID='init', method='initialize', params={'inputRouting': True})))
        bridge._ready = True
        bridge.route_input('@maltose fixture', TurnContext(user_id='owner', speaker_status='identified'), 'voice', 0, 'queued')
        bridge._dispatch('submit_routed_voice', dict(messageID='queued', runtimeSessionID=bridge.session_id, text='fixture'))
        bridge.route_input('unrecognized voice', TurnContext(speaker_status='unknown'), 'voice', 0, 'unknown')
        publish = hub.publish
        def observe(kind, payload):
            publish(kind, payload)
            if kind == 'input_deferred': deferred.set()
        hub.publish = observe
        worker = threading.Thread(target=agent.run); worker.start()
        try: self.assertTrue(deferred.wait(2)); self.assertEqual(calls, [])
        finally: agent.request_shutdown(); worker.join(3)
        self.assertFalse(worker.is_alive())

    def test_codex_panel_executor_uses_current_owner_shared_schema_and_filesystem_boundary(self):
        with tempfile.TemporaryDirectory() as directory:
            service = self.service(directory); calls = []
            service.workspace = lambda operation, identity: {'phase': 'ready'} if operation == 'inspect' and identity == 'fixture' else self.fail('Unexpected workspace')
            bridge = NativeRuntimeBridge(EventHub(), output_stream=io.StringIO(), collaboration=service); self.addCleanup(bridge.close)
            bridge.brain = SimpleNamespace(_identity_is_known=lambda: True, _active_user_id='owner')
            schema = dict(type='object', additionalProperties=False, properties={'panelID': {'type': 'string'}}, required=['panelID'])
            definitions = [dict(name='maltose_read_panel', command='read_panel', inputSchema=schema),
                dict(name='maltose_chart_open_csv', command='chart_open_csv', inputSchema=dict(type='object',additionalProperties=False,
                    properties={'panelID': {'type': 'string'}, 'path': {'type': 'string'}},required=['panelID','path']))]
            bridge.receive_line(json.dumps(dict(schemaVersion=1, requestID='init', method='initialize', params={'tools': definitions})))
            lease = bridge.control.pause(CONTROL_OWNER)
            params = dict(ownerID=CONTROL_OWNER,leaseID=lease['leaseID'],taskID='fixture',ownerSpeakerID='owner',
                          tool='maltose_read_panel',arguments={'panelID': 'notes'})
            bridge.call_panel = lambda command: calls.append(command) or {'ok': True}
            # A persisted task owner must not inherit a previous brain's private identity.
            self.assertEqual(bridge._dispatch('execute_codex_panel', params)['error']['code'], 'identity_required')
            bridge.brain._identity_is_known = lambda: False
            self.assertTrue(bridge._dispatch('execute_codex_panel', {**params, 'uiContextConsent': True})['ok'])
            self.assertEqual(bridge._voice_scope, None, 'UI consent must not create a verified speaker')
            self.assertFalse(bridge.brain._identity_is_known(), 'UI consent must not grant Memory identity')
            calls.clear()
            bridge.observe_voice_context(TurnContext(user_id='owner',speaker_status='identified'))
            self.assertTrue(bridge._dispatch('execute_codex_panel', params)['ok'])
            self.assertEqual(calls, [{'read_panel': {'panelID': 'notes'}}])
            invalid = {**params, 'arguments': {'panelID': 'notes', 'unexpected': True}}
            self.assertEqual(bridge._dispatch('execute_codex_panel', invalid)['error']['code'], 'invalid_argument')
            self.assertEqual(bridge._dispatch('execute_codex_panel', {**params, 'ownerSpeakerID': 'other'})['error']['code'], 'identity_required')
            with self.assertRaises(PermissionError): bridge._dispatch('execute_codex_panel', {**params,'leaseID': 'stale'})
            with self.assertRaises(ValueError): bridge._dispatch('execute_codex_panel', {**params,'tool': 'unsafe_filesystem_read'})
            # The same FileService boundary applies; Swift never opens an arbitrary path.
            denied = bridge._dispatch('execute_codex_panel', {**params,'tool': 'maltose_chart_open_csv',
                'arguments': {'panelID': 'chart','path': '/private/fixture.csv'}})
            self.assertEqual(denied['error']['code'], 'access_denied')
            self.assertEqual(len(calls), 1)
            bridge.observe_voice_context(TurnContext(speaker_status='unknown'))
            self.assertEqual(bridge._dispatch('execute_codex_panel', params)['error']['code'], 'identity_required')

    def test_async_controller_does_not_block_reader_rejects_resume_and_deduplicates(self):
        with tempfile.TemporaryDirectory() as directory:
            service = self.service(directory); output = io.StringIO()
            bridge = NativeRuntimeBridge(EventHub(), output_stream=output, collaboration=service); self.addCleanup(bridge.close)
            bridge.receive_line(json.dumps(dict(schemaVersion=1, requestID='init', method='initialize')))
            bridge.agent = SimpleNamespace(state=SimpleNamespace(value='standby')); bridge._ready = True
            lease = bridge.control.pause(CONTROL_OWNER)
            entered, release = threading.Event(), threading.Event(); calls = []
            def workspace(operation, task_id):
                calls.append(task_id); entered.set(); release.wait(3); return {'phase': 'ready'}
            service.workspace = workspace
            params = dict(ownerID=CONTROL_OWNER, leaseID=lease['leaseID'], taskID='fixture')
            request = dict(schemaVersion=1, requestID='prepare', method='workspace_prepare', params=params)
            try:
                bridge.receive_line(json.dumps(request)); self.assertTrue(entered.wait(1))
                bridge.receive_line(json.dumps(request))
                with self.assertRaises(RuntimeError): bridge._dispatch('resume_autonomy', {**params, 'intentConfirmed': True})
                bridge.receive_line(json.dumps(dict(schemaVersion=1, requestID='snapshot', method='snapshot')))
                self.assertTrue(any(json.loads(line).get('requestID') == 'snapshot' for line in output.getvalue().splitlines()))
                release.set()
                deadline = time.monotonic() + 2
                while bridge._async_requests and time.monotonic() < deadline: time.sleep(.005)
                bridge.receive_line(json.dumps(request)); self.assertEqual(calls, ['fixture'])
                with self.assertRaises(PermissionError): bridge._dispatch('workspace_inspect', {**params, 'leaseID': 'stale'})
            finally: release.set()

    def test_observation_is_source_data_scoped_to_native_input_or_verified_voice_owner(self):
        with tempfile.TemporaryDirectory() as directory:
            brain = TaskBrain(SimpleNamespace(), memory=MemoryStore(Path(directory) / 'memory.json'))
            brain.collaboration_context = dict(taskID='fixture', ownerSpeakerID='owner', summary='Untrusted content', messages=[])
            unknown = TurnContext(user_id='unknown', speaker_status='unknown', input_source='voice')
            self.assertEqual(brain._collaboration_messages(unknown), [])
            native = TurnContext(user_id='unknown', speaker_status='unknown', input_source='native')
            messages = brain._collaboration_messages(native)
            self.assertEqual(messages[0]['role'], 'assistant')
            self.assertFalse(json.loads(messages[0]['content'])['trusted_as_instruction'])
            self.assertFalse(brain._identity_is_known())
            brain._active_user_id = 'owner'; brain._active_speaker_status = 'identified'
            owner = TurnContext(user_id='owner', speaker_status='identified', input_source='voice')
            self.assertTrue(brain._collaboration_messages(owner))
            brain._active_user_id = 'other'
            self.assertEqual(brain._collaboration_messages(owner), [])

    def test_human_repository_selection_is_persisted_and_keeps_old_workspace_authorization(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory); repositories = [root / 'first', root / 'second']
            for repository in repositories:
                repository.mkdir()
                for arguments in [('init', '--quiet'), ('-c', 'user.name=Fixture', '-c', 'user.email=fixture@example.invalid',
                        '-c', 'core.hooksPath=/dev/null', 'commit', '--allow-empty', '--quiet', '-m', 'fixture')]:
                    subprocess.run(['/usr/bin/git', '-C', str(repository), *arguments], check=True, capture_output=True)
            service = NativeCollaborationService(root / 'config', repositories[0])
            first_id = '11111111-1111-4111-8111-111111111111'
            receipt = service.workspace('prepare', first_id)
            service.select_repository(str(repositories[1]))
            self.assertEqual(service.repository, repositories[1].resolve())
            self.assertEqual(service.workspace('inspect', first_id)['worktree'], receipt['worktree'])
            restored = NativeCollaborationService(root / 'config', repositories[0])
            self.assertEqual(restored.repository, repositories[1].resolve())
            self.assertEqual(restored.workspace('changes', first_id)['changes'], [])
            nested = repositories[1] / 'nested'; nested.mkdir()
            with self.assertRaises(ValueError): restored.select_repository(str(nested))
            self.assertEqual(restored.repository, repositories[1].resolve())

    def test_late_main_approval_cannot_promote_or_publish_after_control_handoff(self):
        bridge = NativeRuntimeBridge(EventHub(), output_stream=io.StringIO()); self.addCleanup(bridge.close)
        bridge.receive_line(json.dumps(dict(schemaVersion=1, requestID='init', method='initialize')))
        calls = []
        bridge.action_handler = lambda action, _: calls.append(action)
        bridge.control.pause(CONTROL_OWNER)
        for domain in ('filesystem', 'execution', 'knowledge'):
            with self.assertRaises(RuntimeError): bridge._dispatch('ui_action', {'actionID': domain + '.approve', 'value': {}})
        self.assertEqual(calls, [])
        bridge._dispatch('ui_action', {'actionID': 'execution.reject', 'value': {}})
        self.assertEqual(calls, ['execution.reject'])
        state = bridge.control.snapshot()
        bridge.control.resume(CONTROL_OWNER, state['leaseID'], intent_confirmed=True)
        def approve(action, _):
            state = bridge.control.pause(CONTROL_OWNER)
            self.assertEqual(state['state'], 'pausing')
            self.assertEqual(state['activities'], {'approval': 1})
            calls.append(action)
        bridge.action_handler = approve
        bridge._dispatch('ui_action', {'actionID': 'execution.approve', 'value': {}})
        self.assertEqual(bridge.control.snapshot()['state'], 'paused')
        self.assertEqual(calls, ['execution.reject', 'execution.approve'])


if __name__ == '__main__': unittest.main()
