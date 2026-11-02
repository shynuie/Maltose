"""Durable background results: real SQLite, verified ownership, delivery faults."""
import io
import json
from pathlib import Path
import tempfile
import threading
import time
from types import SimpleNamespace
import unittest
from unittest.mock import patch

from maltose.agent import AgentConfig, VoiceAgent, TaskBrain, TaskManager, TaskStore, MemoryStore, FunctionTaskWorker
from maltose.presentation import AnswerResult
from maltose.runtime import EventHub
from maltose.ui.native import NativeRuntimeBridge


class TaskResultDeliveryTests(unittest.TestCase):
    def completed(self, store, *, user='owner', body='完整內容\n' * 100 + 'https://example.com/source\n```python\npass\n```'):
        task = store.create('背景研究', 'local', user_id=user)
        store.update(task.id, status='succeeded', progress=100, result_summary=body, notification_kind='completion')
        return task

    def brain(self, store, directory):
        model = SimpleNamespace(complete=lambda messages, tools: {'choices': [{'message': {'content': '{"spoken_summary":"背景工作有回報，完成條件仍待核對。"}'}}]})
        brain = TaskBrain(model, memory=MemoryStore(Path(directory)/'memory.json'))
        brain.task_manager = SimpleNamespace(store=store)
        brain._active_user_id = 'owner'; brain._active_speaker_status = 'identified'; brain._active_input_source = 'voice'
        return brain

    def agent(self, brain, receipts):
        events = []; speech = []
        hub = EventHub(); hub.publish = lambda kind, payload: events.append((kind, payload))
        agent = VoiceAgent(config=AgentConfig(interruptible_tts=False), brain=brain, event_hub=hub,
                           speaker=SimpleNamespace(synthesize=lambda request: speech.append(request.text)))
        agent.durable_result_delivery = True
        agent.result_handler = receipts
        return agent, events, speech

    def test_completion_and_outbox_are_one_transaction_and_reopen_preserves_full_result(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory)/'tasks.sqlite3'; store = TaskStore(path)
            task = store.create('atomic completion', 'local', user_id='owner')
            with patch.object(store, '_insert_notification', side_effect=RuntimeError('fixture transaction failure')):
                with self.assertRaises(RuntimeError):
                    store.update(task.id, status='succeeded', result_summary='retained', notification_kind='completion')
            self.assertEqual(store.get(task.id).status, 'pending')
            self.assertEqual(store.pending_notifications('owner'), [])
            final = store.update(task.id, status='succeeded', result_summary='retained', notification_kind='completion')
            notification = store.pending_notifications('owner')[0]
            store.enqueue_notification(final)
            self.assertEqual(len(store.pending_notifications('owner')), 1)
            store.close()
            restored = TaskStore(path)
            try:
                recovered = restored.pending_notifications('owner')[0]
                self.assertEqual(recovered['notification_id'], notification['notification_id'])
                self.assertEqual(recovered['result_summary'], 'retained')
                self.assertTrue(recovered['recovered'])
            finally: restored.close()

    def test_late_reporting_error_does_not_reclassify_success_or_repeat_worker(self):
        with tempfile.TemporaryDirectory() as directory:
            store = TaskStore(Path(directory)/'tasks.sqlite3'); manager = TaskManager(store)
            calls = []
            worker = FunctionTaskWorker(lambda data: calls.append(data) or 'actual result')
            task = store.create('post-completion fault', 'local', user_id='owner')
            def report(record):
                if record.status == 'succeeded': raise RuntimeError('reporting fault after result commit')
            try:
                with patch.object(manager, '_publish_progress', side_effect=report):
                    with self.assertRaises(RuntimeError): manager._run_admitted(task.id, worker)
                self.assertEqual(store.get(task.id).status, 'succeeded')
                self.assertEqual(store.pending_notifications('owner')[0]['result_summary'], 'actual result')
                self.assertEqual(len(calls), 1)
            finally: manager.shutdown(); store.close()

    def test_owner_scoping_and_superseded_progress_do_not_leak_or_publish_old_progress(self):
        with tempfile.TemporaryDirectory() as directory:
            store = TaskStore(Path(directory)/'tasks.sqlite3')
            try:
                task = store.create('progress', 'local', user_id='owner')
                progress = store.update(task.id, status='running', progress=25)
                store.enqueue_notification(progress, kind='progress')
                identity = store.pending_notifications('owner')[0]['notification_id']
                self.assertEqual(store.pending_notifications('someone'), [])
                with self.assertRaises(KeyError): store.prepare_notification_result(identity, 'someone', {})
                with self.assertRaises(KeyError): store.acknowledge_notification(identity, 'someone')
                self.assertFalse(store.claim_notification_speech(identity, 'someone'))
                store.update(task.id, status='succeeded', result_summary='complete', notification_kind='completion')
                remaining = store.pending_notifications('owner')
                self.assertEqual([item['kind'] for item in remaining], ['completion'])
                with self.assertRaises(KeyError): store.acknowledge_notification(identity, 'owner')
            finally: store.close()

    def test_prepared_result_is_stable_and_unverified_identity_cannot_read_it(self):
        with tempfile.TemporaryDirectory() as directory:
            store = TaskStore(Path(directory)/'tasks.sqlite3')
            try:
                self.completed(store)
                brain = self.brain(store, directory)
                first = brain.pending_task_results()[0]
                self.assertIn('https://example.com/source', first['result'].full_text)
                self.assertIn('```python', first['result'].full_text)
                self.assertEqual(first['result'].kind, 'partial')
                self.assertEqual(brain.pending_task_results()[0]['result'], first['result'])
                brain._active_speaker_status = 'unknown'
                self.assertEqual(brain.pending_task_results(), [])
                with self.assertRaises(PermissionError): brain.acknowledge_task_result(first['notification_id'])
                self.assertEqual(len(store.pending_notifications('owner')), 1)
            finally: store.close()

    def test_unknown_delivery_stays_pending_then_acknowledges_once_without_reexecuting(self):
        with tempfile.TemporaryDirectory() as directory:
            store = TaskStore(Path(directory)/'tasks.sqlite3')
            try:
                task = self.completed(store)
                calls = []; accepted = False
                def deliver(result):
                    calls.append(result)
                    return {'status': 'chat_only' if accepted else 'delivery_unknown', 'chatStored': accepted}
                brain = self.brain(store, directory)
                agent, events, speech = self.agent(brain, deliver)
                agent._speak_task_notifications()
                self.assertEqual(len(store.pending_notifications('owner')), 1)
                self.assertEqual(speech, [])
                agent._speak_task_notifications()
                self.assertEqual(len(calls), 1, 'Unknown delivery uses bounded retry backoff')
                accepted = True; agent._notification_retry_after.clear()
                agent._speak_task_notifications(); agent._speak_task_notifications()
                self.assertEqual(len(calls), 2)
                self.assertEqual(calls[0].result_id, calls[1].result_id)
                self.assertEqual(store.pending_notifications('owner'), [])
                self.assertEqual(len(speech), 1)
                self.assertEqual(store.get(task.id).status, 'succeeded')
                self.assertEqual([p['message_id'] for k, p in events if k == 'assistant_start'], [calls[0].result_id] * 2)
            finally: store.close()

    def test_recovered_pending_result_is_delivered_as_text_without_replaying_old_speech(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory)/'tasks.sqlite3'; store = TaskStore(path)
            self.completed(store); original = self.brain(store, directory).pending_task_results()[0]['result']
            store.close(); restored = TaskStore(path)
            try:
                brain = self.brain(restored, directory)
                calls = []
                agent, events, speech = self.agent(brain, lambda result: calls.append(result) or {'status': 'chat_only', 'chatStored': True})
                agent._speak_task_notifications()
                self.assertEqual(calls, [original])
                self.assertEqual(speech, [])
                self.assertEqual(restored.pending_notifications('owner'), [])
                self.assertTrue(any(k == 'speech_cancelled' and p['reason'] == 'recovered_or_claimed_notification' for k, p in events))
            finally: restored.close()

    def test_unpresentable_result_is_retained_without_crashing_or_marking_delivered(self):
        with tempfile.TemporaryDirectory() as directory:
            store = TaskStore(Path(directory)/'tasks.sqlite3')
            try:
                self.completed(store, body='x' * (256 * 1024 + 1))
                brain = self.brain(store, directory)
                with self.assertLogs('maltose.agent.taskbrain', level='ERROR'): self.assertEqual(brain.pending_task_results(), [])
                self.assertEqual(len(store.pending_notifications('owner')[0]['result_summary']), 256 * 1024 + 1)
            finally: store.close()

    def test_native_durable_ack_requires_negotiation_and_matching_saved_publication(self):
        bridge = NativeRuntimeBridge(EventHub(), output_stream=io.StringIO()); self.addCleanup(bridge.close)
        bridge.receive_line(json.dumps(dict(schemaVersion=1, requestID='init', method='initialize',
            params=dict(presentationVersion=1, resultDeliveryVersion=1, conversationID='conversation'))))
        self.assertEqual(bridge.result_delivery_version, 1)
        result = AnswerResult('完整結果', '摘要', chat_message_id='stream-message')
        packets = []
        def deliver(command):
            packets.append(command)
            return {'ok': True, 'result': {'publicationID': result.result_id, 'chatStored': True, 'panelStatus': 'none', 'replayed': False}}
        bridge.call_panel = deliver
        self.assertTrue(bridge.present_result(result)['chatStored'])
        self.assertEqual(packets[0]['deliver_result']['messageID'], 'stream-message')
        self.assertEqual(packets[0]['deliver_result']['conversationID'], 'conversation')
        for receipt in ({'chatStored': True}, {'publicationID': 'wrong', 'chatStored': True, 'panelStatus': 'none'},
                        {'publicationID': result.result_id, 'chatStored': False, 'panelStatus': 'none'}):
            bridge.call_panel = lambda command, value=receipt: {'ok': True, 'result': value}
            self.assertFalse(bridge.present_result(result)['chatStored'])

    def test_unlinked_or_legacy_background_notification_cannot_attach_to_last_main_task(self):
        with tempfile.TemporaryDirectory() as directory:
            store = TaskStore(Path(directory) / 'tasks.sqlite3')
            bridge = NativeRuntimeBridge(EventHub(), output_stream=io.StringIO()); self.addCleanup(bridge.close)
            brain = self.brain(store, directory)
            brain._active_input_id = 'main-human'
            brain._active_workflow_ref = dict(taskID='last-main-task', inputID='main-human', requirementsRevision=1, planVersion=1)
            bridge.brain = brain; bridge.presentation_version = 1; bridge.result_delivery_version = 1; bridge.workflow_version = 1
            packets = []
            def deliver(command):
                packets.append(command)
                self.assertIn('deliver_result', command, 'A background notification must not send a mainResult workflow operation')
                return {'ok': True, 'result': {'publicationID': command['deliver_result']['publicationID'], 'chatStored': True, 'panelStatus': 'none'}}
            bridge.call_panel = deliver
            try:
                self.completed(store, body='舊排程回報')
                first = brain.pending_task_results()[0]
                self.assertEqual(first['result'].delivery_origin, 'background')
                # Simulate a prepared v1 notification saved before this optional field existed.
                legacy = first['result'].to_record(); legacy.pop('delivery_origin')
                store._connection.execute('UPDATE task_notifications SET result_json=? WHERE id=?', (json.dumps(legacy), first['notification_id']))
                store._connection.commit()
                restored = brain.pending_task_results()[0]['result']
                self.assertEqual(restored.delivery_origin, 'background')
                self.assertTrue(bridge.present_result(restored)['chatStored'])
                self.assertEqual(len(packets), 1)
                self.assertEqual(restored.result_id, first['result'].result_id)
            finally: store.close()

    def test_cancelled_worker_late_return_preserves_cancellation_and_cannot_be_retried_while_active(self):
        with tempfile.TemporaryDirectory() as directory:
            store = TaskStore(Path(directory)/'tasks.sqlite3'); manager = TaskManager(store)
            entered = threading.Event(); release = threading.Event(); calls = []
            def work(data):
                calls.append(data); entered.set()
                if not release.wait(3): raise TimeoutError('fixture did not release')
                return '取消後才返回的完整結果。' * 50
            manager.register_worker('fixture', FunctionTaskWorker(work))
            try:
                task = manager.create_plan([dict(title='取消測試', worker_type='fixture')], user_id='owner')[0]
                self.assertTrue(entered.wait(1))
                self.assertEqual(manager.cancel(task.id, 'owner')['status'], 'cancelled')
                with self.assertRaises(RuntimeError): manager.retry(task.id, 'owner')
                release.set()
                deadline = time.monotonic() + 2
                while not store.get(task.id).result_summary and time.monotonic() < deadline: time.sleep(.01)
                self.assertEqual(store.get(task.id).status, 'cancelled')
                self.assertIn('取消後才返回', store.get(task.id).result_summary)
                self.assertEqual(len(calls), 1)
                agent, events, speech = self.agent(self.brain(store, directory), lambda result: {'chatStored': True, 'status': 'chat_only'})
                deliveries = agent.brain.pending_task_results()
                self.assertTrue(all(item['cancelled'] and not item['result'].needs_document for item in deliveries))
                agent._speak_task_notifications()
                self.assertEqual(speech, [])
                self.assertEqual(store.pending_notifications('owner'), [])
                self.assertTrue(any(k == 'speech_cancelled' and p['reason'] == 'cancelled_task' for k, p in events))
            finally: release.set(); manager.shutdown(); store.close()

    def test_invalid_large_results_do_not_hide_later_valid_result_and_remain_saved(self):
        with tempfile.TemporaryDirectory() as directory:
            store = TaskStore(Path(directory)/'tasks.sqlite3')
            try:
                for _ in range(3): self.completed(store, body='x' * (256 * 1024 + 1))
                good = self.completed(store, body='有效結果')
                brain = self.brain(store, directory)
                with self.assertLogs('maltose.agent.taskbrain', level='ERROR'):
                    deliveries = brain.pending_task_results(limit=1)
                self.assertEqual(len(deliveries), 1)
                self.assertIn('有效結果', deliveries[0]['result'].full_text)
                self.assertEqual(len(store.pending_notifications('owner', 100)), 4)
                self.assertEqual(store.get(good.id).result_summary, '有效結果')
            finally: store.close()

    def test_invalid_delivery_version_cannot_enable_new_command_for_older_clients(self):
        for presentation, delivery in [(1, True), (1, 2), (0, 1)]:
            with self.subTest(presentation=presentation, delivery=delivery):
                output = io.StringIO()
                bridge = NativeRuntimeBridge(EventHub(), output_stream=output)
                try:
                    bridge.receive_line(json.dumps(dict(schemaVersion=1, requestID='init', method='initialize',
                        params=dict(presentationVersion=presentation, resultDeliveryVersion=delivery))))
                    self.assertFalse(json.loads(output.getvalue().splitlines()[-1])['ok'])
                    self.assertEqual(bridge.result_delivery_version, 0)
                finally: bridge.close()

    def test_legacy_recovery_adapter_does_not_replay_old_complete_answer(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory)/'tasks.sqlite3'; store = TaskStore(path)
            self.completed(store, body='不應重新朗讀的舊答案 https://example.com/old')
            store.close(); restored = TaskStore(path)
            try:
                brain = self.brain(restored, directory)
                brain.task_manager = SimpleNamespace(store=restored, drain_notifications=restored.drain_notifications)
                messages = brain.consume_task_notifications()
                self.assertEqual(len(messages), 1)
                self.assertIn('先前保存', messages[0])
                self.assertNotIn('舊答案', messages[0]); self.assertNotIn('https://', messages[0])
                self.assertEqual(brain.consume_task_notifications(), [])
            finally: restored.close()

    def test_long_background_summary_receives_complete_source_including_final_limitation(self):
        from maltose.presentation import SpeechPolicy
        with tempfile.TemporaryDirectory() as directory:
            store = TaskStore(Path(directory)/'tasks.sqlite3')
            try:
                body = '公開測試資料。' * 2500 + '\n最後的重要限制：真實來源仍未核對。'
                self.completed(store, body=body)
                brain = self.brain(store, directory)
                source = brain.pending_task_results()[0]['result']
                calls = []
                def complete(messages, tools):
                    calls.append((messages, tools))
                    supplied = json.loads(messages[-1]['content'])
                    self.assertEqual(supplied['full_text'], source.full_text)
                    self.assertIn('最後的重要限制', supplied['full_text'])
                    return {'choices': [{'message': {'content': '{"spoken_summary":"公開測試資料已有回報，真實來源仍未核對。"}'}}]}
                brain.model = SimpleNamespace(complete=complete)
                repaired = brain.repair_spoken_summary(source, SpeechPolicy())
                self.assertEqual(len(calls), 1); self.assertEqual(calls[0][1], [])
                self.assertEqual(repaired.full_text, source.full_text)
                self.assertIn('來源仍未核對', repaired.spoken_summary)
            finally: store.close()
