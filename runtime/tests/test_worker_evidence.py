import json
from pathlib import Path
import tempfile
import threading
import time
from types import SimpleNamespace
import unittest
from unittest.mock import patch
import uuid

from maltose.agent import TaskStore, TaskManager, FunctionTaskWorker, ToolRegistry, TaskBrain, MemoryStore, VoiceAgent, AgentConfig
from maltose.presentation import AnswerResult
from maltose.agent.search import WebResearchWorker, SearchResult
from maltose.tool_observations import collect_tool_returns
from maltose.ui.workflow import NativeWorkflowToolAdapter


class WorkerEvidenceTests(unittest.TestCase):
    def wait(self, condition):
        deadline = time.monotonic() + 3
        while not condition() and time.monotonic() < deadline: time.sleep(.01)
        self.assertTrue(condition())

    def bind(self, records):
        return {r.id: dict(schemaVersion=1, taskID=str(uuid.uuid4()), inputID='human', executionID='python:' + r.id,
                           requirementsRevision=1, planVersion=1) for r in records}

    def admit(self, record, identity):
        return {**record.workflow, 'executionID': 'python:' + record.id + ':' + identity, 'attemptID': identity}

    def test_real_registry_returns_are_copied_and_two_worker_threads_never_share_receipts(self):
        with tempfile.TemporaryDirectory() as directory:
            store = TaskStore(Path(directory) / 'tasks.db'); manager = TaskManager(store, max_workers=2)
            manager.attempt_observer = self.admit
            registry = ToolRegistry(); barrier = threading.Barrier(2)
            registry.register('read_file', 'fixture', {}, lambda args: dict(root='fixture', path=args['path'], text=args['path'], bytes=len(args['path'])))
            def work(data):
                barrier.wait(2)
                result = registry.execute('read_file', data)
                result['text'] = 'mutated after return'
                return 'self-report claiming arbitrary tests passed'
            manager.register_worker('fixture', FunctionTaskWorker(work))
            try:
                records = manager.create_plan([dict(title=name, worker_type='fixture', input=dict(path=name)) for name in ['one', 'two']],
                    user_id='owner', plan_observer=self.bind)
                self.wait(lambda: all(store.get(r.id).status == 'succeeded' for r in records))
                registry.execute('read_file', {'path': 'outside-worker'})
                completions = [n for n in store.pending_notifications('owner', 100) if n['kind'] == 'completion']
                self.assertEqual(len(completions), 2)
                for n in completions:
                    ref = n['attempt_workflow']; actual = store.attempt(ref['attemptID'], 'owner')
                    self.assertEqual(actual['phase'], 'finished'); self.assertEqual(actual['workflow'], ref)
                    self.assertEqual(len(actual['observations']), 1)
                    self.assertEqual(actual['observations'][0]['result']['text'], n['title'])
                    with self.assertRaises(KeyError): store.attempt(ref['attemptID'], 'other-owner')
            finally: manager.shutdown(); store.close()

    def test_unknown_attempt_acknowledgement_does_not_run_worker_and_is_durable(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / 'tasks.db'; store = TaskStore(path); calls = []
            manager = TaskManager(store, workers={'fixture': FunctionTaskWorker(lambda data: calls.append(data))})
            def unknown(record, identity):
                self.assertEqual(store.attempt(identity, 'owner')['phase'], 'prepared')
                raise TimeoutError('ACK lost')
            manager.attempt_observer = unknown
            try:
                with self.assertRaises(TimeoutError): manager.create_plan([dict(title='work', worker_type='fixture')], user_id='owner', plan_observer=self.bind)
                task = store.list('owner')[0]
                self.assertEqual(task.status, 'held'); self.assertEqual(calls, [])
                with self.assertRaises(ValueError): store.begin_attempt(task.id, uuid.uuid4().hex)
            finally: manager.shutdown(); store.close()
            restored = TaskStore(path)
            try:
                self.assertEqual(restored.get(task.id).status, 'held')
                with self.assertRaises(ValueError): restored.begin_attempt(task.id, uuid.uuid4().hex)
            finally: restored.close()

    def test_retry_retains_distinct_attempts_and_first_result_provenance(self):
        with tempfile.TemporaryDirectory() as directory:
            store = TaskStore(Path(directory) / 'tasks.db'); manager = TaskManager(store); ids = []; calls = []
            def admit(record, identity): ids.append(identity); return self.admit(record, identity)
            manager.attempt_observer = admit
            def work(data):
                calls.append(data)
                if len(calls) == 1: raise RuntimeError('first actual attempt failed')
                return 'second actual attempt returned'
            manager.register_worker('fixture', FunctionTaskWorker(work))
            try:
                task = manager.create_plan([dict(title='retry', worker_type='fixture')], user_id='owner', plan_observer=self.bind)[0]
                self.wait(lambda: store.get(task.id).status == 'failed' and not manager._futures)
                first = [n for n in store.pending_notifications('owner', 100) if n['kind'] == 'completion'][0]
                manager.retry(task.id, user_id='owner'); self.wait(lambda: store.get(task.id).status == 'succeeded')
                self.assertEqual(len(ids), 2); self.assertNotEqual(ids[0], ids[1])
                completions = [n for n in store.pending_notifications('owner', 100) if n['kind'] == 'completion']
                self.assertEqual([n['attempt_workflow']['attemptID'] for n in completions], ids)
                self.assertEqual(completions[0], first)
                self.assertEqual(store.attempt(ids[0], 'owner')['phase'], 'finished')
            finally: manager.shutdown(); store.close()

    def test_lost_admission_acknowledgement_retries_same_unstarted_identity_and_executes_once(self):
        with tempfile.TemporaryDirectory() as directory:
            store = TaskStore(Path(directory) / 'tasks.db'); manager = TaskManager(store); ids = []; calls = []
            def admit(record, identity):
                ids.append(identity)
                if len(ids) == 1: raise TimeoutError('Accepted by host but ACK lost')
                return self.admit(record, identity)
            manager.attempt_observer = admit
            manager.register_worker('fixture', FunctionTaskWorker(lambda data: calls.append(data) or 'actual result'))
            try:
                with self.assertRaises(TimeoutError): manager.create_plan([dict(title='work', worker_type='fixture')], user_id='owner', plan_observer=self.bind)
                task = store.list('owner')[0]
                self.assertEqual(calls, [])
                manager.retry(task.id, user_id='owner'); self.wait(lambda: store.get(task.id).status == 'succeeded')
                self.assertEqual(len(ids), 2); self.assertEqual(ids[0], ids[1]); self.assertEqual(len(calls), 1)
                self.assertEqual(store.attempt(ids[0], 'owner')['phase'], 'finished')
            finally: manager.shutdown(); store.close()

    def test_queued_cancel_preserves_known_unstarted_attempt_and_retry_runs_only_new_attempt(self):
        with tempfile.TemporaryDirectory() as directory:
            store = TaskStore(Path(directory) / 'tasks.db'); manager = TaskManager(store, max_workers=1)
            release = threading.Event(); entered = threading.Event(); calls = []
            def work(data):
                calls.append(data['step'])
                if data['step'] == 1:
                    entered.set(); self.assertTrue(release.wait(3))
                return 'actual result'
            manager.attempt_observer = self.admit; manager.register_worker('fixture', FunctionTaskWorker(work))
            try:
                first = manager.create_plan([dict(title='first', worker_type='fixture', input={'step': 1})], user_id='owner', plan_observer=self.bind)[0]
                self.assertTrue(entered.wait(2))
                second = manager.create_plan([dict(title='second', worker_type='fixture', input={'step': 2})], user_id='owner', plan_observer=self.bind)[0]
                old = manager._attempts[second.id]; manager.cancel(second.id, user_id='owner')
                self.assertEqual(store.attempt(old, 'owner')['phase'], 'finished')
                report = store.completed_attempt_reports(second.id, 'owner')[0]
                self.assertEqual(report['attemptID'], old); self.assertEqual(report['workerState'], 'cancelled')
                release.set(); self.wait(lambda: store.get(first.id).status == 'succeeded')
                manager.retry(second.id, user_id='owner'); self.wait(lambda: store.get(second.id).status == 'succeeded')
                self.assertEqual(calls, [1, 2])
                self.assertNotEqual(store.completed_attempt_reports(second.id, 'owner')[-1]['attemptID'], old)
            finally: release.set(); manager.shutdown(); store.close()

    def test_retry_reconciles_prior_terminal_fact_before_new_host_admission_without_acknowledging_chat(self):
        with tempfile.TemporaryDirectory() as directory:
            store = TaskStore(Path(directory) / 'tasks.db'); manager = TaskManager(store); operations = []; count = []
            def transport(operation, **arguments):
                operations.append(operation)
                if operation == 'pythonResult': return {'schemaVersion': 1}
                record = store.get(arguments['workerID'])
                return {'attemptBinding': self.admit(record, arguments['attemptID'])}
            adapter = NativeWorkflowToolAdapter(SimpleNamespace(brain=SimpleNamespace(task_manager=manager), call_workflow=transport))
            manager.attempt_observer = adapter.admit_worker_attempt
            def work(data):
                count.append('run')
                if len(count) == 1: raise RuntimeError('first failed')
                return 'second succeeded'
            manager.register_worker('fixture', FunctionTaskWorker(work))
            try:
                task = manager.create_plan([dict(title='work', worker_type='fixture')], user_id='owner', plan_observer=self.bind)[0]
                self.wait(lambda: store.get(task.id).status == 'failed' and not manager._futures)
                manager.retry(task.id, user_id='owner'); self.wait(lambda: store.get(task.id).status == 'succeeded')
                self.assertEqual(operations, ['pythonAttempt', 'pythonResult', 'pythonAttempt'])
                self.assertEqual(len([n for n in store.pending_notifications('owner', 100) if n['kind'] == 'completion']), 2)
            finally: manager.shutdown(); store.close()

    def test_terminal_status_evidence_and_notification_are_one_transaction(self):
        with tempfile.TemporaryDirectory() as directory:
            store = TaskStore(Path(directory) / 'tasks.db'); task = store.create('work', 'fixture', user_id='owner')
            identity = uuid.uuid4().hex; store.begin_attempt(task.id, identity); store.admit_attempt(identity, None); store.mark_attempt_running(identity)
            try:
                with patch.object(store, '_insert_notification', side_effect=OSError('disk failure')):
                    with self.assertRaises(OSError): store.update(task.id, status='succeeded', result_summary='actual result',
                        attempt_id=identity, observations=[{'receipt': 'actual'}], notification_kind='completion')
                self.assertEqual(store.get(task.id).status, 'running')
                self.assertEqual(store.attempt(identity, 'owner')['observations'], [])
                self.assertEqual(store.attempt(identity, 'owner')['phase'], 'running')
                self.assertEqual(store.pending_notifications('owner'), [])
            finally: store.close()

    def test_search_worker_records_actual_provider_return_as_snippets_not_page_reads(self):
        provider = SimpleNamespace(search=lambda *args, **kwargs: [SearchResult(title='Actual provider fixture', url='https://example.com', snippet='Search snippet only')])
        worker = WebResearchWorker(provider)
        with collect_tool_returns() as receipts:
            body = worker.run(SimpleNamespace(input={'queries': ['fixture']}), lambda progress: None)
        self.assertIn('https://example.com', body)
        self.assertEqual(receipts[0]['tool'], 'search_web')
        self.assertEqual(receipts[0]['result']['granularity'], 'search_results')

    def test_aggregate_contains_only_acknowledged_same_owner_task_and_versions_and_progress_is_not_a_terminal_report(self):
        with tempfile.TemporaryDirectory() as directory:
            store = TaskStore(Path(directory) / 'tasks.db')
            reference = dict(schemaVersion=1, taskID=str(uuid.uuid4()), inputID='human', requirementsRevision=1, planVersion=1,
                executionID='python:job:attempt', attemptID=uuid.uuid4().hex)
            try:
                for owner, changes, accepted in [('owner', {}, True), ('owner', {}, False), ('other', {}, True),
                                                  ('owner', {'taskID': str(uuid.uuid4())}, True), ('owner', {'requirementsRevision': 2}, True)]:
                    task = store.create('publication', 'fixture', user_id=owner)
                    store.update(task.id, status='succeeded', result_summary='full', notification_kind='completion')
                    item = store.pending_notifications(owner, 100)[-1]
                    result = AnswerResult('完整已交付結果', '', workflow_ref={**reference, **changes}, delivery_origin='background')
                    store.prepare_notification_result(item['notification_id'], owner, result.to_record())
                    if accepted: store.acknowledge_notification(item['notification_id'], owner)
                delivered = store.delivered_product_results('owner', reference)
                self.assertTrue(delivered['complete']); self.assertEqual(len(delivered['results']), 1)
                self.assertEqual(delivered['results'][0]['full_text'], '完整已交付結果')
                self.assertTrue(delivered['results'][0]['chatStored'])
                task = store.create('progress', 'fixture', user_id='owner')
                store.bind_workflow([task], {task.id: {key: value for key, value in {**reference, 'executionID': 'python:' + task.id}.items() if key != 'attemptID'}})
                store.update(task.id, progress=25, notification_kind='progress')
                brain = TaskBrain(SimpleNamespace(), memory=MemoryStore(Path(directory) / 'memory.json'))
                brain.task_manager = SimpleNamespace(store=store)
                brain._active_user_id = 'owner'
                item = next(n for n in store.pending_notifications('owner', 100) if n['task_id'] == task.id)
                result = brain._prepare_task_result(item)
                self.assertIsNone(result.workflow_ref, 'Progress is not a worker terminal fact or a Main result')
                self.assertEqual(result.delivery_origin, 'background')
            finally: store.close()

    def test_private_payloads_and_overflow_are_not_promoted_to_complete_worker_evidence(self):
        registry = ToolRegistry()
        registry.register('recall', 'private', {}, lambda args: {'secret': 'private-memory'})
        registry.register('read_file', 'read', {}, lambda args: {'text': 'fixture'})
        with collect_tool_returns() as receipts:
            registry.execute('recall', {})
            self.assertEqual(receipts, [])
            for _ in range(70): registry.execute('read_file', {})
        self.assertEqual(len(receipts), 64); self.assertTrue(receipts[-1]['truncated'])

    def test_background_spoken_status_follows_host_assessment_and_preserves_full_report(self):
        for status in ['completed', 'partial']:
            with self.subTest(status=status):
                spoken = []
                result = AnswerResult('worker 原始自述：全部測試通過。完整資料與連結仍保留。', '', kind='partial', delivery_origin='background',
                    limitations=('這是背景工作的執行回報，整體需求的完成條件仍需核對。',))
                brain = SimpleNamespace(pending_task_results=lambda: [dict(notification_id='notice', result=result, recovered=False)],
                    acknowledge_task_result=lambda identity: True, repair_spoken_summary=lambda result, policy: result,
                    _active_user_id='owner', _active_speaker_status='identified', _active_input_source='voice')
                agent = VoiceAgent(config=AgentConfig(interruptible_tts=False), brain=brain,
                    speaker=SimpleNamespace(synthesize=lambda request: spoken.append(request.text)))
                agent.result_handler = lambda result: {'chatStored': True, 'workflowStored': True,
                    'workflowAssessment': {'status': status, 'summary': '本機內容已核對，公開來源仍未查核。'}}
                agent._deliver_task_results()
                self.assertTrue(spoken); self.assertEqual(agent._last_result.full_text, result.full_text)
                if status == 'completed':
                    self.assertIn('公開來源仍未查核', spoken[0]); self.assertNotIn('整體需求的完成條件仍需核對', spoken[0])
                else:
                    self.assertIn('公開來源仍未查核', spoken[0]); self.assertNotIn('全部測試通過', spoken[0])


if __name__ == '__main__': unittest.main()
