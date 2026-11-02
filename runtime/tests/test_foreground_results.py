"""Real SQLite foreground outbox: no synthetic worker, principal or tool replay."""
from dataclasses import replace
from pathlib import Path
from types import SimpleNamespace
import tempfile
import unittest
from unittest.mock import patch

from maltose.agent import TaskStore, VoiceAgent, AgentConfig
from maltose.agent.brain import TurnContext
from maltose.foreground_results import ForegroundResultService
from maltose.presentation import AnswerResult, ResultChart
from maltose.runtime import EventHub


class ForegroundResultTests(unittest.TestCase):
    def fixture(self, directory, *, task=False):
        store = TaskStore(Path(directory)/'tasks.sqlite3'); self.addCleanup(store.close)
        reference = dict(taskID='task', inputID='human', requirementsRevision=1, planVersion=1) if task else None
        brain = SimpleNamespace(task_manager=SimpleNamespace(store=store), _active_input_id='human', _active_workflow_ref=reference,
            _active_user_id=None, _active_speaker_status='unknown')
        bridge = SimpleNamespace(brain=brain, conversation_id='conversation', session_id='a'*32, result_chart_version=1,
            workflow=SimpleNamespace(observations=lambda ref: [dict(id='b'*32, tool='read_file', result={'text': 'receipt'})]),
            agent=SimpleNamespace(_publish=lambda *args: None))
        service = ForegroundResultService(bridge); bridge.foreground=service
        state = dict(current=True, calls=[], deliveries=[], assessment=None)
        def workflow(operation, **args):
            state['calls'].append(operation)
            row = store.foreground_result(args.get('resultID', args.get('foregroundPublication', {}).get('publicationID')), 'conversation')
            if operation == 'foregroundPrepare': return dict(current=state['current'],superseded=not state['current'])
            if operation == 'foregroundDelivered':
                if state['assessment']: return dict(assessment=state['assessment'])
                return dict(assessmentContext=dict(criteria=['交付全文'], evidence=[{'id':'receipt'}])) if task else {}
            if operation == 'assessResult':
                self.assertIsNotNone(row['assessment'], 'Review must be saved before native submission')
                state['assessment'] = args['assessment']
            return dict(assessment=state['assessment'])
        def deliver(result):
            state['deliveries'].append(result)
            self.assertEqual(store.foreground_result(result.result_id.split(':assessment')[0], 'conversation')['phase'], 'pending')
            return dict(chatStored=True, panelID='panel', chartStatus='applied' if result.chart else 'none')
        bridge.call_workflow=workflow; bridge._deliver_result=deliver
        return service, bridge, store, state

    def prepare(self, service, *, chart=False):
        data = ResultChart.from_dict(dict(title='測試圖', caption='使用者提供虛構資料', xTitle='日期', series=['數量'],
            rows=[dict(x='2026-01',values=[1],note='使用者提供'),dict(x='2026-02',values=[2],note='使用者提供')])) if chart else None
        return service.prepare(AnswerResult('完整結果與限制。', '短摘要。', chat_message_id='stream-message', chart=data),
            context=TurnContext(input_source='native', input_id='human'))

    def test_foreground_negotiation_requires_real_conversation_and_existing_protocols(self):
        from maltose.ui.native import NativeRuntimeBridge
        import io
        complete=dict(presentationVersion=1,resultDeliveryVersion=1,workflowVersion=1,inputScopeVersion=1,foregroundResultVersion=1,conversationID='conversation')
        for change in ({'foregroundResultVersion':True},{'foregroundResultVersion':2},{'inputScopeVersion':0},{'resultDeliveryVersion':0},{'conversationID':None}):
            bridge=NativeRuntimeBridge(EventHub(),output_stream=io.StringIO()); self.addCleanup(bridge.close)
            with self.assertRaises(ValueError): bridge._dispatch('initialize',{**complete,**change})
        bridge=NativeRuntimeBridge(EventHub(),output_stream=io.StringIO()); self.addCleanup(bridge.close)
        self.assertEqual(bridge._dispatch('initialize',complete)['foregroundResultVersion'],1)

    def test_save_before_publish_scoped_immutable_and_no_fake_worker_or_memory_owner(self):
        with tempfile.TemporaryDirectory() as directory:
            service, bridge, store, state = self.fixture(directory)
            result = self.prepare(service, chart=True)
            row = store.foreground_result(result.result_id, 'conversation')
            self.assertEqual(row['payload']['principal'], dict(userID=None,status='unknown',source='native'))
            self.assertEqual(AnswerResult.from_record(row['payload']['result']), result)
            self.assertEqual(service.prepare(result), result)
            self.assertEqual(store._connection.execute('SELECT count(*) FROM tasks').fetchone()[0], 0)
            self.assertEqual(store._connection.execute('SELECT count(*) FROM task_notifications').fetchone()[0], 0)
            with self.assertRaises(KeyError): store.foreground_result(result.result_id, 'another-conversation')
            with self.assertRaises(ValueError): store.prepare_foreground_result('conversation', {**row['payload'], 'inputID':'another-human'})
            receipt = service.deliver(result.result_id)
            self.assertTrue(receipt['chatStored']); self.assertTrue(receipt['foregroundSpeechAllowed'])
            self.assertFalse(service.deliver(result.result_id)['foregroundSpeechAllowed'])
            self.assertEqual(len(state['deliveries']), 1)
            self.assertIsNone(bridge.brain._active_user_id)

    def test_reopen_after_lost_ack_replays_saved_chart_and_source_without_reexecuting(self):
        with tempfile.TemporaryDirectory() as directory:
            service, bridge, store, state = self.fixture(directory)
            result = self.prepare(service, chart=True)
            def lost(result): raise TimeoutError('UI may already have stored it')
            bridge._deliver_result = lost
            self.assertFalse(service.deliver(result.result_id)['workflowStored'])
            store.close()
            restored, new_bridge, reopened, new_state = self.fixture(directory)
            new_bridge.session_id='c'*32
            receipt = restored.deliver(result.result_id, retry=True)
            self.assertTrue(receipt['workflowStored']); self.assertFalse(receipt['foregroundSpeechAllowed'])
            self.assertEqual(new_state['deliveries'], [result])
            self.assertEqual(reopened.foreground_result(result.result_id, 'conversation')['payload']['producerSessionID'], 'a'*32)
            self.assertIsNone(new_bridge.brain._active_user_id)

    def test_saved_identified_voice_never_promotes_an_unknown_recovery_principal(self):
        with tempfile.TemporaryDirectory() as directory:
            service, bridge, store, state = self.fixture(directory)
            result=service.prepare(AnswerResult('原授權回答','短摘要'),context=TurnContext(user_id='original-owner',speaker_status='identified',input_source='voice',input_id='human'))
            restored,new_bridge,reopened,new_state=self.fixture(directory)
            new_bridge.session_id='d'*32; new_bridge.brain._active_input_id=None
            receipt=restored.deliver(result.result_id,retry=True)
            self.assertTrue(receipt['workflowStored']); self.assertFalse(receipt['foregroundSpeechAllowed'])
            self.assertIsNone(new_bridge.brain._active_user_id)
            self.assertEqual(new_bridge.brain._active_speaker_status,'unknown')
            self.assertEqual(reopened.foreground_result(result.result_id,'conversation')['payload']['principal']['userID'],'original-owner')

    def test_new_input_supersedes_saved_facts_without_ui_or_audio(self):
        with tempfile.TemporaryDirectory() as directory:
            service, bridge, store, state = self.fixture(directory, task=True)
            result = self.prepare(service); state['current']=False
            receipt = service.deliver(result.result_id)
            self.assertEqual(receipt['status'], 'superseded'); self.assertFalse(receipt['foregroundSpeechAllowed'])
            self.assertEqual(state['deliveries'], [])
            row = store.foreground_result(result.result_id, 'conversation')
            self.assertEqual(row['phase'], 'superseded'); self.assertEqual(len(row['payload']['observations']), 1)

    def test_temporary_pause_keeps_result_pending_instead_of_discarding_source(self):
        with tempfile.TemporaryDirectory() as directory:
            service, bridge, store, state = self.fixture(directory)
            result = self.prepare(service)
            bridge.call_workflow=lambda operation,**args: dict(current=False,superseded=False)
            self.assertFalse(service.deliver(result.result_id)['workflowStored'])
            self.assertEqual(store.foreground_result(result.result_id,'conversation')['phase'],'pending')
            self.assertEqual(state['deliveries'],[])

    def test_malformed_review_context_keeps_saved_body_pending_without_claiming_speech(self):
        with tempfile.TemporaryDirectory() as directory:
            service, bridge, store, state = self.fixture(directory, task=True)
            result=self.prepare(service); original=bridge.call_workflow
            bridge.call_workflow=lambda operation,**args: dict(assessmentContext=['invalid']) if operation=='foregroundDelivered' else original(operation,**args)
            receipt=service.deliver(result.result_id)
            self.assertEqual(receipt['deliveryError'],'ValueError')
            self.assertFalse(receipt['workflowStored']);self.assertFalse(receipt['foregroundSpeechAllowed'])
            self.assertEqual(store.foreground_result(result.result_id,'conversation')['phase'],'pending')
            bridge.call_workflow=original
            with patch('maltose.workflow_verification.assess_result',return_value=None):
                self.assertTrue(service.deliver(result.result_id,retry=True)['workflowStored'])
            self.assertEqual(state['deliveries'],[result,result])

    def test_review_is_saved_before_submission_and_lost_ack_never_repeats_model_review(self):
        with tempfile.TemporaryDirectory() as directory:
            service, bridge, store, state = self.fixture(directory, task=True)
            result = self.prepare(service)
            original=bridge.call_workflow
            def lost(operation, **args):
                response=original(operation, **args)
                if operation=='assessResult': raise TimeoutError('Accepted review response lost')
                return response
            bridge.call_workflow=lost
            assessment=dict(status='partial', summary='尚缺原始問卷。', checks=[],remaining=['取得原始問卷'],resolvedFailures={},explanation='僅有摘要')
            with patch('maltose.workflow_verification.assess_result', return_value=assessment) as review:
                self.assertFalse(service.deliver(result.result_id)['workflowStored'])
                bridge.call_workflow=original
                receipt=service.deliver(result.result_id)
            self.assertTrue(receipt['workflowStored']); self.assertEqual(review.call_count, 1)
            self.assertEqual(state['deliveries'][-1].result_id, result.result_id+':assessment')
            self.assertIn('原始問卷', state['deliveries'][-1].full_text)

    def test_voice_final_waits_for_durable_ack_and_unacknowledged_result_never_speaks(self):
        for acknowledged in (False, True):
            with tempfile.TemporaryDirectory() as directory:
                service, bridge, store, state = self.fixture(directory)
                events=[]; speech=[]; calls=[]; at_publish=[]
                hub=EventHub(); hub.publish=lambda kind,payload: events.append((kind,payload))
                result=AnswerResult('完整回答', '短摘要。')
                bridge.brain.process_result=lambda text,context: calls.append(text) or result
                agent=VoiceAgent(config=AgentConfig(interruptible_tts=False),brain=bridge.brain,event_hub=hub,
                    speaker=SimpleNamespace(synthesize=lambda request:speech.append(request.text)))
                agent.result_preparer=service.prepare
                def publish(value):
                    at_publish.append(len(events))
                    self.assertFalse(any(kind=='assistant_end' for kind,payload in events))
                    self.assertTrue(store.pending_foreground_results('conversation'))
                    return dict(chatStored=acknowledged,workflowStored=acknowledged,foregroundSpeechAllowed=acknowledged)
                agent.result_handler=publish
                agent._respond_to_input('問題',TurnContext(input_source='voice',input_id='human'))
                self.assertEqual(calls,['問題'])
                self.assertEqual(bool(speech),acknowledged)
                self.assertEqual(any(kind=='assistant_end' for kind,payload in events),acknowledged)
                self.assertFalse(any(kind=='assistant_delta' for kind,payload in events[at_publish[0]:]), 'Do not append deltas after durable native replacement')


if __name__=='__main__': unittest.main()
