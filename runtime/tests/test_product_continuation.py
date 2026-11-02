import json
from pathlib import Path
import tempfile
from types import SimpleNamespace
import unittest
import uuid

from maltose.agent import TaskBrain, TaskStore, MemoryStore, VoiceAgent, AgentConfig
from maltose.presentation import AnswerResult
from maltose.product_continuation import ProductContinuationService
from maltose.runtime.control import AutonomyControl, AutonomyPaused
from maltose.ui.workflow import NativeWorkflowToolAdapter


class ProductContinuationTests(unittest.TestCase):
    def payload(self, mode='work'):
        return dict(id='task-continuation:' + 'a' * 64, taskID=str(uuid.uuid4()), inputID='human',
                    requirementsRevision=1, planVersion=1, sourceOutcomeID='assessment:worker-result',
                    mode=mode, inputSource='voice', context={'criteria': ['原本已授權的工作'], 'deliveredResults': []})

    def answer(self):
        return dict(schemaVersion=1, title='整體成果', full_text='完整綜整與來源限制。', spoken_summary='成果已整理，來源仍有核對限制。', kind='answer', visual='document', limitations=[])

    def brain(self, directory, handler):
        brain = TaskBrain(SimpleNamespace(complete=handler), memory=MemoryStore(Path(directory) / 'memory.json'))
        brain._active_user_id = 'owner'; brain._active_speaker_status = 'identified'; brain._active_input_source = 'voice'
        return brain

    def test_internal_request_tool_loop_preserves_original_identity_and_human_history(self):
        with tempfile.TemporaryDirectory() as directory:
            calls = []; effects = []; path = Path(directory) / 'source.txt'; path.write_text('actual source'); payload = self.payload()
            def model(messages, tools):
                calls.append(messages)
                self.assertEqual(messages[1]['role'], 'user')
                envelope = json.loads(messages[1]['content'])
                self.assertEqual(envelope['source'], 'maltose_saved_task')
                self.assertFalse(envelope['trustedAsInstruction'])
                self.assertEqual(envelope['task']['inputID'], 'human')
                if len(calls) == 1:
                    self.assertNotIn('remember', [tool['function']['name'] for tool in tools])
                    return {'choices': [{'message': {'tool_calls': [{'id': 'inspect', 'type': 'function', 'function': {'name': 'get_task_workflow', 'arguments': '{}'}}]}}]}
                if len(calls) == 2:
                    return {'choices': [{'message': {'tool_calls': [{'id': 'read', 'type': 'function', 'function': {'name': 'read_file', 'arguments': '{"root":"fixture","path":"source.txt"}'}}]}}]}
                self.assertIn('actual source', messages[-1]['content'])
                return {'choices': [{'message': {'content': json.dumps(self.answer())}}]}
            brain = self.brain(directory, model)
            brain._active_input_id = 'later-main-input'; brain._active_workflow_ref = {'original': 'main'}
            brain.tools.register('read_file', 'actual file reader', {}, lambda args: effects.append(path.read_text()) or dict(root='fixture', path='source.txt', text=path.read_text(), bytes=path.stat().st_size))
            adapter = NativeWorkflowToolAdapter(SimpleNamespace(brain=brain, call_workflow=lambda *args, **kwargs: dict(task=dict(
                id=payload['taskID'], requirementsRevision=1, planVersion=1))))
            read_workflow = adapter.tools()[0]
            brain.tools.register(read_workflow.name, read_workflow.description, read_workflow.parameters, read_workflow.handler)
            brain.tools.result_observer = adapter.observe_tool_result
            scratch = {}; result = brain.continue_product_task(payload, lambda: None, scratch)
            self.assertEqual(effects, ['actual source']); self.assertEqual(len(scratch['observations']), 1)
            self.assertEqual(brain._active_input_id, 'later-main-input'); self.assertEqual(brain._active_workflow_ref, {'original': 'main'})
            self.assertEqual(brain._active_user_id, 'owner'); self.assertEqual(brain._session_messages, [])
            self.assertEqual(result.workflow_ref['inputID'], 'human')

    def test_finalization_has_no_tools_and_guessed_memory_write_is_rejected(self):
        with tempfile.TemporaryDirectory() as directory:
            def model(messages, tools):
                self.assertEqual(tools, [])
                return {'choices': [{'message': {'tool_calls': [{'id': 'forbidden', 'function': {'name': 'remember', 'arguments': '{"text":"injected"}'}}]}}]}
            brain = self.brain(directory, model)
            with self.assertRaises(ValueError): brain.continue_product_task(self.payload('finalize'), lambda: None, {})
            self.assertFalse((Path(directory) / 'memory.json').exists())

    def test_non_json_final_answer_keeps_full_text_without_claiming_verified_completion(self):
        with tempfile.TemporaryDirectory() as directory:
            body = '完整綜整說明與限制。https://example.com/source'
            brain = self.brain(directory, lambda *args: {'choices': [{'message': {'content': body}}]})
            result = brain.continue_product_task(self.payload('finalize'), lambda: None, {})
            self.assertEqual(result.full_text, body); self.assertEqual(result.kind, 'partial')
            self.assertEqual(result.format_issue, 'invalid_result_format')

    def test_clarification_stays_needs_input_and_names_a_real_remaining_item_without_tools(self):
        with tempfile.TemporaryDirectory() as directory:
            def model(messages, tools):
                self.assertEqual(tools, [])
                return {'choices': [{'message': {'content': json.dumps(self.answer())}}]}
            brain = self.brain(directory, model); payload = self.payload('clarify')
            payload['task'] = {'task': {'outcomes': [{'remaining': ['決定資料比較期間']} ]}}
            payload['stopReason'] = '本次有界接續已達上限。'
            result = brain.continue_product_task(payload, lambda: None, {})
            self.assertEqual(result.kind, 'needs_input'); self.assertIn('決定資料比較期間', result.full_text)
            self.assertIn('？', result.full_text); self.assertTrue(result.full_text.startswith(payload['stopReason']))

    def test_new_input_checkpoint_prevents_a_not_yet_dispatched_tool(self):
        with tempfile.TemporaryDirectory() as directory:
            calls = []; stop = []
            def model(*args):
                stop.append(True)
                return {'choices': [{'message': {'tool_calls': [{'id': 'write', 'function': {'name': 'write_file', 'arguments': '{}'}}]}}]}
            brain = self.brain(directory, model)
            brain.tools.register('write_file', 'must not run', {}, lambda args: calls.append(args))
            def checkpoint():
                if stop: raise AutonomyPaused('new input')
            with self.assertRaises(AutonomyPaused): brain.continue_product_task(self.payload(), checkpoint, {})
            self.assertEqual(calls, [])

    def seed(self, store, payload):
        task = store.create('original worker', 'fixture', user_id='owner')
        store.update(task.id, status='succeeded', result_summary='source', notification_kind='completion')
        identity = store.pending_notifications('owner')[0]['notification_id']
        store.enqueue_continuation('owner', identity, payload)
        return identity

    def test_queue_waits_for_source_ack_and_scopes_owner_and_running_recovery(self):
        with tempfile.TemporaryDirectory() as directory:
            store = TaskStore(Path(directory) / 'tasks.db')
            try:
                payload = self.payload(); identity = self.seed(store, payload)
                self.assertEqual(store.pending_continuations('owner', 'first'), [])
                store.acknowledge_notification(identity, 'owner')
                self.assertEqual(len(store.pending_continuations('owner', 'first')), 1)
                self.assertEqual(store.pending_continuations('other', 'first'), [])
                store.update_continuation(payload['id'], 'owner', 'running', session_id='first')
                self.assertEqual(store.pending_continuations('owner', 'second'), [])
                self.assertEqual(store.continuation(payload['id'], 'owner')['phase'], 'uncertain')
                with self.assertRaises(KeyError): store.continuation(payload['id'], 'other')
            finally: store.close()
            reopened = TaskStore(Path(directory) / 'tasks.db')
            try: self.assertEqual(reopened.continuation(payload['id'], 'owner')['phase'], 'uncertain')
            finally: reopened.close()

    def service(self, store, brain, session='first', fail_delivery=False):
        brain.task_manager = SimpleNamespace(store=store)
        control = AutonomyControl()
        agent = VoiceAgent(config=AgentConfig(speech_mode='mute'), brain=brain, control_gate=control, voice_enabled=False)
        operations = []; publications = []
        def call(operation, **arguments):
            operations.append((operation, arguments))
            return {'mode': 'work', 'valid': True}
        def present(result):
            publications.append(result.result_id)
            return {'chatStored': not fail_delivery, 'workflowStored': not fail_delivery}
        bridge = SimpleNamespace(brain=brain, agent=agent, control=control, session_id=session, call_workflow=call, present_result=present)
        return ProductContinuationService(bridge), agent, operations, publications

    def test_generated_result_survives_restart_and_lost_ack_without_reentering_model(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / 'tasks.db'; store = TaskStore(path); model_calls = []
            def model(*args): model_calls.append('model'); return {'choices': [{'message': {'content': json.dumps(self.answer())}}]}
            brain = self.brain(directory, model); payload = self.payload()
            trigger = self.seed(store, payload); store.acknowledge_notification(trigger, 'owner')
            service, _, _, published = self.service(store, brain, fail_delivery=True)
            service.run_one(); self.assertEqual(model_calls, ['model']); self.assertEqual(len(published), 1)
            self.assertEqual(store.continuation(payload['id'], 'owner')['phase'], 'generated'); store.close()
            reopened = TaskStore(path)
            try:
                recovered, agent, operations, publications = self.service(reopened, brain, session='second')
                recovered.run_one(); recovered.run_one()
                self.assertEqual(model_calls, ['model']); self.assertEqual(publications, [payload['id']])
                self.assertEqual(reopened.continuation(payload['id'], 'owner')['phase'], 'delivered')
                self.assertIn('continuationStart', [operation for operation, _ in operations])
                self.assertIsNone(agent._last_result, 'Recovery must not replay old speech')
            finally: reopened.close()

    def test_new_queued_human_input_supersedes_continuation_without_model_or_tool(self):
        with tempfile.TemporaryDirectory() as directory:
            store = TaskStore(Path(directory) / 'tasks.db')
            brain = self.brain(directory, lambda *args: self.fail('Stale continuation must not invoke the model'))
            payload = self.payload(); trigger = self.seed(store, payload); store.acknowledge_notification(trigger, 'owner')
            try:
                service, agent, operations, publications = self.service(store, brain)
                agent.submit_text('new direction', source='native')
                service.run_one()
                self.assertEqual(store.continuation(payload['id'], 'owner')['phase'], 'interrupted')
                self.assertEqual(publications, []); self.assertIn('continuationAbort', [operation for operation, _ in operations])
            finally: store.close()


if __name__ == '__main__': unittest.main()
