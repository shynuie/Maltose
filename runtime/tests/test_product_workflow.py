"""Product/worker boundary: dispatch ordering, provenance and durable receipts."""
import io
import json
from pathlib import Path
import tempfile
import threading
from types import SimpleNamespace
import unittest
import uuid

from maltose.agent import TaskStore, TaskManager, TaskBrain, MemoryStore, FunctionTaskWorker, VoiceAgent, AgentConfig
from maltose.agent.tasks import TaskPlanNotDispatched
from maltose.presentation import AnswerResult
from maltose.runtime import EventHub
from maltose.ui.native import NativeRuntimeBridge
from maltose.ui.workflow import NativeWorkflowToolAdapter


class ProductWorkflowTests(unittest.TestCase):
    def test_scope_tool_requires_explicit_protocol_negotiation_and_rejects_invalid_versions(self):
        for value in (True, -1, 2, '1'):
            bridge = NativeRuntimeBridge(EventHub(), output_stream=io.StringIO()); self.addCleanup(bridge.close)
            with self.assertRaises(ValueError): bridge._dispatch('initialize', dict(workflowVersion=1, inputScopeVersion=value))
        bridge = NativeRuntimeBridge(EventHub(), output_stream=io.StringIO()); self.addCleanup(bridge.close)
        with self.assertRaises(ValueError): bridge._dispatch('initialize', dict(inputScopeVersion=1))
        response = bridge._dispatch('initialize', dict(workflowVersion=1))
        self.assertEqual(response['inputScopeVersion'], 0)
        self.assertNotIn('set_task_scope', [tool.name for tool in NativeWorkflowToolAdapter(bridge).tools()])
        negotiated = NativeRuntimeBridge(EventHub(), output_stream=io.StringIO()); self.addCleanup(negotiated.close)
        self.assertEqual(negotiated._dispatch('initialize', dict(workflowVersion=1, inputScopeVersion=1))['inputScopeVersion'], 1)
        self.assertIn('set_task_scope', [tool.name for tool in NativeWorkflowToolAdapter(negotiated).tools()])

    def test_reading_an_unbound_previous_task_never_gives_its_reference_to_the_current_answer(self):
        brain = SimpleNamespace(_active_input_id='new-human', _active_workflow_ref=None)
        task = dict(id=str(uuid.uuid4()), requirementsRevision=3, planVersion=2)
        adapter = NativeWorkflowToolAdapter(SimpleNamespace(brain=brain, call_workflow=lambda *args, **kwargs: dict(task=task, inputBound=False)))
        self.assertEqual(adapter.snapshot()['task'], task)
        self.assertIsNone(brain._active_workflow_ref)

    def test_scope_tool_uses_saved_input_and_fresh_host_version_without_accepting_model_identity(self):
        brain = SimpleNamespace(_active_input_id='actual-human', _active_workflow_ref=None)
        task = dict(id=str(uuid.uuid4()), requirementsRevision=2, planVersion=1); calls = []
        def call(operation, **arguments):
            calls.append((operation, arguments))
            return dict(task=task, inputBound=operation=='relateInput', inputRelation='continueTask')
        adapter = NativeWorkflowToolAdapter(SimpleNamespace(brain=brain, call_workflow=call, input_scope_version=1))
        tool = next(value for value in adapter.tools() if value.name=='set_task_scope')
        for injected in ({'inputID':'forged'}, {'runtimeSessionID':'forged'}, {'taskID':'forged'}):
            self.assertEqual(tool.handler(dict(relation='continueTask', **injected))['error'], 'workflow_rejected')
        self.assertEqual(calls, [])
        tool.handler({'relation':'continueTask'})
        self.assertEqual(calls[-1], ('relateInput', dict(relation='continueTask', taskID=task['id'], expectedRequirementsRevision=2)))
        self.assertEqual(brain._active_workflow_ref['inputID'], 'actual-human')
        self.assertEqual(brain._active_workflow_ref['requirementsRevision'], 2)

    def binding(self, record, revision=1):
        return dict(schemaVersion=1, taskID=str(uuid.uuid4()), inputID='human-source',
                    executionID='python:' + record.id, requirementsRevision=revision, planVersion=1)

    def test_observer_failure_holds_all_prepared_work_without_dispatch_or_automatic_retry(self):
        with tempfile.TemporaryDirectory() as directory:
            store = TaskStore(Path(directory) / 'tasks.sqlite3')
            calls = []
            manager = TaskManager(store, workers={'fixture': FunctionTaskWorker(lambda data: calls.append(data))})
            observed = []
            def unavailable(records):
                observed.extend(records)
                raise TimeoutError('Host saved the plan but its acknowledgement was lost')
            try:
                with self.assertRaises(TaskPlanNotDispatched) as raised:
                    manager.create_plan([dict(title='first', worker_type='fixture'), dict(title='second', worker_type='fixture')],
                                        user_id='owner', plan_observer=unavailable)
                self.assertEqual(len(observed), 2)
                self.assertTrue(all(record.status == 'pending' for record in observed))
                self.assertTrue(all(record.status == 'held' for record in raised.exception.records))
                self.assertTrue(all(not store.get(record.id).dispatch_ready for record in raised.exception.records))
                for record in raised.exception.records: manager._schedule_if_ready(record.id)
                self.assertEqual(calls, [])
                self.assertEqual(store.pending_notifications('owner'), [])
            finally: manager.shutdown(); store.close()

    def test_actual_worker_sees_persisted_binding_before_start_and_notification_keeps_original_revision(self):
        with tempfile.TemporaryDirectory() as directory:
            store = TaskStore(Path(directory) / 'tasks.sqlite3')
            finished = threading.Event(); observed = []; records = []
            def work(data):
                current = store.get(records[0].id, user_id='owner')
                observed.append(current.workflow)
                finished.set()
                return 'Actual worker result'
            manager = TaskManager(store, workers={'fixture': FunctionTaskWorker(work)})
            def prepare(items):
                records.extend(items)
                return {item.id: self.binding(item, revision=2) for item in items}
            try:
                prepared = manager.create_plan([dict(title='linked work', worker_type='fixture')], user_id='owner', plan_observer=prepare)
                self.assertTrue(finished.wait(2))
                manager.shutdown()
                self.assertEqual(observed, [prepared[0].workflow])
                self.assertEqual(observed[0]['requirementsRevision'], 2)
                notifications = store.pending_notifications('owner')
                self.assertEqual(notifications[-1]['workflow'], observed[0])
                store.close(); store = TaskStore(Path(directory) / 'tasks.sqlite3')
                self.assertEqual(store.get(prepared[0].id).workflow, observed[0])
                self.assertTrue(store.get(prepared[0].id).dispatch_ready)
                self.assertEqual(store.pending_notifications('owner')[-1]['workflow'], observed[0])
            finally: manager.shutdown(); store.close()

    def test_observer_is_scoped_to_one_plan_and_cannot_capture_later_legacy_or_scheduled_work(self):
        with tempfile.TemporaryDirectory() as directory:
            store = TaskStore(Path(directory) / 'tasks.sqlite3')
            manager = TaskManager(store)
            manager._stop_scheduler.set(); manager._scheduler.join()
            observed = []
            def prepare(items):
                observed.extend(items)
                return {item.id: self.binding(item) for item in items}
            try:
                # Unavailable workers fail synchronously; no worker timing is involved.
                linked = manager.create_plan([dict(title='linked', worker_type='unavailable')], plan_observer=prepare)[0]
                legacy = manager.create_plan([dict(title='legacy', worker_type='unavailable')])[0]
                manager.create_schedule('due schedule', 'unavailable', '2020-01-01T00:00:00+00:00')
                for schedule in store.due_schedules(): manager._run_schedule(schedule)
                self.assertEqual([record.id for record in observed], [linked.id])
                self.assertIsNotNone(store.get(linked.id).workflow)
                self.assertIsNone(store.get(legacy.id).workflow)
                scheduled = [record for record in store.list() if record.title == 'due schedule']
                self.assertEqual(len(scheduled), 1)
                self.assertIsNone(scheduled[0].workflow)
            finally: manager.shutdown(); store.close()

    def test_binding_is_immutable_and_invalid_or_foreign_batches_roll_back(self):
        with tempfile.TemporaryDirectory() as directory:
            store = TaskStore(Path(directory) / 'tasks.sqlite3')
            try:
                first = store.create('one', 'local', user_id='owner')
                second = store.create('two', 'local', user_id='owner')
                value = self.binding(first)
                store.bind_workflow([first], {first.id: value})
                self.assertEqual(store.bind_workflow([first], {first.id: value})[0].workflow, value)
                with self.assertRaises(ValueError): store.bind_workflow([first], {first.id: {**value, 'requirementsRevision': 2}})
                for invalid in ({**self.binding(second), 'schemaVersion': True}, {**self.binding(second), 'requirementsRevision': True},
                                {**self.binding(second), 'executionID': 'python:' + first.id}, {**self.binding(second), 'taskID': 'not-a-uuid'}):
                    with self.assertRaises(ValueError): store.bind_workflow([second], {second.id: invalid})
                # The first mutation in a batch must roll back if a later binding conflicts.
                with self.assertRaises(ValueError):
                    store.bind_workflow([second, first], {second.id: self.binding(second), first.id: {**value, 'requirementsRevision': 3}})
                self.assertIsNone(store.get(second.id).workflow)
                self.assertEqual(store.get(first.id).workflow, value)
                store.update(second.id, status='running')
                with self.assertRaises(ValueError): store.bind_workflow([second], {second.id: self.binding(second)})
            finally: store.close()

    def test_an_existing_dependency_finishing_cannot_dispatch_work_while_host_ack_is_pending(self):
        with tempfile.TemporaryDirectory() as directory:
            store = TaskStore(Path(directory) / 'tasks.sqlite3')
            manager = TaskManager(store, max_workers=2)
            entered = threading.Event(); release = threading.Event(); dependency_processed = threading.Event()
            dependent_entered = threading.Event()
            observed = []; prepared = []
            def existing(data):
                entered.set()
                if not release.wait(3): raise TimeoutError('existing fixture worker not released')
                return 'existing work completed'
            def dependent(data):
                observed.append(store.get(prepared[0].id).workflow)
                dependent_entered.set()
                return 'new work completed'
            manager.register_worker('existing', FunctionTaskWorker(existing))
            manager.register_worker('dependent', FunctionTaskWorker(dependent))
            original = manager._schedule_dependents
            try:
                dependency = manager.create_plan([dict(title='existing', worker_type='existing')], user_id='owner')[0]
                self.assertTrue(entered.wait(1))
                def advance(identity):
                    original(identity)
                    if identity == dependency.id: dependency_processed.set()
                manager._schedule_dependents = advance
                def host_ack(records):
                    prepared.extend(records)
                    release.set()
                    self.assertTrue(dependency_processed.wait(2))
                    self.assertEqual(store.get(records[0].id).status, 'pending', 'No dispatch before the host acknowledgement')
                    reopened = TaskStore(Path(directory) / 'tasks.sqlite3')
                    try: self.assertFalse(reopened.get(records[0].id).dispatch_ready, 'Unacknowledged admission must survive a new store connection')
                    finally: reopened.close()
                    return {record.id: self.binding(record) for record in records}
                linked = manager.create_plan([dict(title='new', worker_type='dependent', dependencies=[dependency.id])],
                                             user_id='owner', plan_observer=host_ack)[0]
                self.assertTrue(dependent_entered.wait(2), 'Wait for execution before shutdown cancels queued futures')
                manager.shutdown()
                self.assertEqual(observed, [linked.workflow])
                self.assertIsNotNone(observed[0])
                self.assertEqual(store.get(linked.id).status, 'succeeded')
            finally: release.set(); manager.shutdown(); store.close()

    def test_model_cannot_supply_input_or_runtime_identity_and_native_planning_does_not_unlock_private_tasks(self):
        with tempfile.TemporaryDirectory() as directory:
            store = TaskStore(Path(directory) / 'tasks.sqlite3'); manager = TaskManager(store)
            brain = TaskBrain(SimpleNamespace(), memory=MemoryStore(Path(directory) / 'memory.json'), task_manager=manager)
            brain._active_input_id = 'actual-human-input'
            calls = []
            def call(operation, **arguments):
                calls.append((operation, arguments))
                return {'schemaVersion': 1, 'task': None}
            adapter = NativeWorkflowToolAdapter(SimpleNamespace(brain=brain, call_workflow=call))
            plan = next(tool for tool in adapter.tools() if tool.name == 'set_task_plan')
            arguments = dict(criteria=['preserve full result'], steps=[dict(id='one', title='produce result', dependencies=[])])
            try:
                self.assertEqual(plan.handler({**arguments, 'inputID': 'forged'})['error'], 'workflow_rejected')
                self.assertEqual(plan.handler({**arguments, 'runtimeSessionID': 'forged'})['error'], 'workflow_rejected')
                self.assertEqual(calls, [])
                plan.handler(arguments)
                self.assertEqual(calls[-1][1]['plan']['sourceInputID'], 'actual-human-input')
                self.assertFalse(brain._identity_is_known())
                result = brain._create_product_linked_plan({'tasks': [dict(title='private job', worker_type='local')]})
                self.assertEqual(result, brain._identity_required_error())
                self.assertEqual(store.list(), [])
            finally: manager.shutdown(); store.close()

    def test_workflow_command_requires_negotiation_and_runtime_supplies_envelope_identity(self):
        bridge = NativeRuntimeBridge(EventHub(), output_stream=io.StringIO()); self.addCleanup(bridge.close)
        bridge.brain = SimpleNamespace(_active_input_id='actual-input')
        packets = []
        bridge.call_panel = lambda packet: packets.append(packet) or {'ok': True, 'result': {'schemaVersion': 1, 'task': None}}
        with self.assertRaises(RuntimeError): bridge.call_workflow('read')
        self.assertEqual(packets, [])
        bridge.workflow_version = 1
        bridge.call_workflow('read', schemaVersion=99, runtimeSessionID='forged')
        request = packets[0]['workflow']['request']
        self.assertEqual(request['runtimeSessionID'], bridge.session_id)
        self.assertEqual(request['schemaVersion'], 1)
        self.assertEqual(request['inputID'], 'actual-input')

    def test_chat_receipt_without_workflow_receipt_retains_notification_and_retries_same_result_once(self):
        with tempfile.TemporaryDirectory() as directory:
            store = TaskStore(Path(directory) / 'tasks.sqlite3')
            brain = TaskBrain(SimpleNamespace(), memory=MemoryStore(Path(directory) / 'memory.json'))
            brain.task_manager = SimpleNamespace(store=store)
            brain._active_user_id = 'owner'; brain._active_speaker_status = 'identified'; brain._active_input_source = 'voice'
            calls = []
            agent = VoiceAgent(config=AgentConfig(interruptible_tts=False), brain=brain)
            agent.durable_result_delivery = True
            def deliver(result):
                calls.append(result.result_id)
                return {'chatStored': True, 'workflowStored': len(calls) > 1}
            agent.result_handler = deliver
            try:
                task = store.create('background', 'local', user_id='owner')
                store.update(task.id, status='succeeded', result_summary='full result', notification_kind='completion')
                agent._speak_task_notifications()
                self.assertEqual(len(store.pending_notifications('owner')), 1)
                agent._notification_retry_after.clear()
                # Avoid audio; this test concerns durable acknowledgement only.
                agent._speak_result = lambda *args, **kwargs: None
                agent._speak_task_notifications(); agent._speak_task_notifications()
                self.assertEqual(len(calls), 2); self.assertEqual(calls[0], calls[1])
                self.assertEqual(store.pending_notifications('owner'), [])
            finally: store.close()


if __name__ == '__main__': unittest.main()
