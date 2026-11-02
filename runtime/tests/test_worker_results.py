import json
from pathlib import Path
import tempfile
from types import SimpleNamespace
import unittest
import uuid

from maltose.agent import TaskBrain,TaskStore,MemoryStore,VoiceAgent,AgentConfig
from maltose.presentation import AnswerResult
from maltose.product_continuation import ProductContinuationService
from maltose.runtime import EventHub
from maltose.runtime.control import AutonomyControl,AutonomyPaused
from maltose.ui.native import NativeRuntimeBridge
from maltose.ui.workflow import NativeWorkflowToolAdapter
from maltose.worker_results import WorkerResultService


class WorkerResultTests(unittest.TestCase):
    def setUp(self):
        self.temporary=tempfile.TemporaryDirectory();self.addCleanup(self.temporary.cleanup)
        self.base=Path(self.temporary.name);self.store=TaskStore(self.base/'tasks.db');self.addCleanup(self.store.close)
        self.source=self.seed('actual-owner');self.other=self.seed('other-owner')
        self.grants=[self.source['grant']];self.calls=[];self.publications=[];self.defer=False
        self.brain=TaskBrain(SimpleNamespace(),memory=MemoryStore(self.base/'memory.json'),task_manager=SimpleNamespace(store=self.store,worker_types=[]))
        self.brain._active_user_id='unknown';self.brain._active_speaker_status='unknown';self.brain._active_input_id='typed-interlude'
        self.control=AutonomyControl();self.agent=VoiceAgent(config=AgentConfig(speech_mode='mute'),brain=self.brain,voice_enabled=False,control_gate=self.control)
        def workflow(operation,**arguments):
            self.calls.append((operation,arguments))
            if operation=='workerPending':return dict(workers=self.grants)
            if operation=='workerPrepare':return dict(deferred=self.defer,resumeAfterID='main-result:'+'a'*32)
            return dict(mode='work',valid=True)
        def present(result):self.publications.append(result);return dict(chatStored=True,workflowStored=True)
        self.bridge=SimpleNamespace(brain=self.brain,agent=self.agent,control=self.control,hub=EventHub(),worker_result_version=1,result_chart_version=1,
            session_id='b'*32,conversation_id='conversation',foreground_continuation_version=1,task_resumption_version=1,call_workflow=workflow,_present_result=present)
        self.service=WorkerResultService(self.bridge);self.bridge.worker_results=self.service
        self.bridge.workflow=NativeWorkflowToolAdapter(self.bridge)
        self.brain.pending_worker_result_provider=self.service.pending;self.brain.pending_worker_result_ids=self.service.pending_ids
    def seed(self,owner,product_id=None):
        task=self.store.create('原授權背景成果','fixture',user_id=owner)
        source=dict(schemaVersion=1,taskID=product_id or str(uuid.uuid4()),inputID='original-'+owner,executionID='python:'+task.id,requirementsRevision=1,planVersion=1)
        self.store.bind_workflow([task],{task.id:source})
        attempt=uuid.uuid4().hex;self.store.begin_attempt(task.id,attempt)
        binding={**source,'executionID':'python:'+task.id+':'+attempt,'attemptID':attempt}
        self.store.admit_attempt(attempt,binding)
        self.store.update(task.id,status='succeeded',result_summary='完整原始資料 17，來源尚未查核。',notification_kind='completion',attempt_id=attempt,observations=[])
        item=next(row for row in self.store.pending_notifications(owner) if row['task_id']==task.id)
        grant={key:binding[key] for key in ('taskID','inputID','requirementsRevision','planVersion','attemptID')};grant['workerID']=task.id;grant['managedResults']=['task-result:'+item['notification_id']]
        return dict(owner=owner,task=task,grant=grant,notification=item['notification_id'],binding=binding)
    def test_native_task_scope_reads_only_original_attempt_without_changing_unknown_principal(self):
        deliveries=self.brain.pending_task_results()
        self.assertEqual([d['notification_id'] for d in deliveries],[self.source['notification']])
        self.assertEqual(deliveries[0]['delivery_owner'],'actual-owner')
        self.assertEqual(self.brain._active_user_id,'unknown');self.assertFalse(self.brain._identity_is_known())
        result=self.brain.tools.execute('recall',dict(query='private'))
        self.assertIn('identity',str(result).lower());self.assertFalse((self.base/'memory.json').exists())
        self.assertEqual(self.store.pending_notifications('other-owner')[0]['prepared_result'],None)
    def test_wrong_worker_attempt_task_input_and_versions_never_select_foreign_notification(self):
        for key,value in [('workerID',self.other['task'].id),('attemptID',self.other['grant']['attemptID']),('taskID',str(uuid.uuid4())),('inputID','fake'),('requirementsRevision',2),('planVersion',2)]:
            with self.subTest(key=key):self.assertEqual(self.store.scoped_product_notifications([{**self.source['grant'],key:value}]),[])
        with self.assertRaises(ValueError):self.store.scoped_product_notifications([{**self.source['grant'],'planVersion':True}])
    def test_scope_also_requires_actual_immutable_attempt_not_just_notification_prose(self):
        self.store._connection.execute("UPDATE task_attempts SET workflow_json='{}' WHERE id=?",(self.source['grant']['attemptID'],));self.store._connection.commit()
        with self.assertRaises(ValueError):self.service.rows()
    def test_deferred_delivery_never_calls_publisher_and_retains_original_pending_body(self):
        result=self.brain.pending_task_results()[0]['result'];self.defer=True
        reply=self.service.deliver(result)
        self.assertFalse(reply['chatStored']);self.assertEqual(self.publications,[])
        self.assertEqual(self.store.pending_notifications('actual-owner')[0]['prepared_result']['result_id'],result.result_id)
    def test_resumption_uses_delivery_reference_without_rewriting_producer_or_owner(self):
        result=self.brain.pending_task_results()[0]['result'];before=self.store.pending_notifications('actual-owner')[0]['prepared_result']
        self.assertTrue(self.service.deliver(result)['chatStored'])
        self.assertEqual(self.publications[0].workflow_ref['resumeAfterID'],'main-result:'+'a'*32)
        self.assertNotIn('resumeAfterID',before['workflow_ref'])
        self.assertEqual(self.store.pending_notifications('actual-owner')[0]['prepared_result'],before)
        self.assertEqual(self.brain._active_user_id,'unknown')
    def test_ack_requires_current_narrow_scope_and_claims_speech_once(self):
        self.assertTrue(self.service.acknowledge(self.source['notification'],'actual-owner'))
        self.assertFalse(self.service.acknowledge(self.source['notification'],'actual-owner'))
        with self.assertRaises(AutonomyPaused):self.service.acknowledge(self.other['notification'],'other-owner')
        self.grants=[]
        with self.assertRaises(AutonomyPaused):self.service.acknowledge(self.source['notification'],'actual-owner')
    def test_native_chat_admission_precedes_any_background_stream_event(self):
        self.agent.result_publication_managed=self.service.managed;self.agent.result_handler=lambda result:dict(chatStored=False)
        self.agent._start_assistant_stream=lambda *args:self.fail('Deferred worker must not enter chat before native admission')
        self.agent._deliver_task_results()
        self.assertEqual(len(self.store.pending_notifications('actual-owner')),1)
    def test_worker_continuations_are_selected_by_granted_trigger_without_identity_rebinding(self):
        result=self.brain.pending_task_results()[0]['result'];reference=result.workflow_ref
        payload=dict(id='task-continuation:'+'c'*64,**{key:reference[key] for key in ('taskID','inputID','requirementsRevision','planVersion')},
            sourceOutcomeID=result.result_id,mode='work',resumeAfterID='main-result:'+'a'*32,context={})
        self.store.acknowledge_notification(self.source['notification'],'actual-owner')
        self.store.enqueue_continuation('actual-owner',self.source['notification'],payload)
        other={**payload,'id':'task-continuation:'+'d'*64,'taskID':self.other['grant']['taskID']}
        self.store.acknowledge_notification(self.other['notification'],'other-owner');self.store.enqueue_continuation('other-owner',self.other['notification'],other)
        service=ProductContinuationService(self.bridge)
        rows=service._rows();self.assertEqual([(key,row['id']) for kind,key,row in rows],[('actual-owner',payload['id'])])
        self.assertEqual(self.brain._active_user_id,'unknown')
    def test_durable_followup_retries_native_context_after_ack_without_publishing_or_reexecuting(self):
        result=self.brain.pending_task_results()[0]['result']
        self.service.acknowledge(self.source['notification'],'actual-owner');self.defer=True
        self.service.retry_one()
        self.assertFalse(self.service.rows()[0]['followup_checked']);self.assertEqual(self.publications,[])
        self.store.close();self.store=TaskStore(self.base/'tasks.db');self.addCleanup(self.store.close)
        self.brain.task_manager.store=self.store;self.defer=False
        self.assertTrue(self.service.due());self.service.retry_one()
        self.assertTrue(self.service.rows()[0]['followup_checked']);self.assertFalse(self.service.due())
        self.assertEqual(self.publications,[]);self.assertEqual(self.brain._active_user_id,'unknown')
        self.assertEqual(self.store.pending_notifications('other-owner')[0]['prepared_result'],None)
    def test_new_queued_input_after_prepare_prevents_native_publication(self):
        result=self.brain.pending_task_results()[0]['result'];original=self.bridge.call_workflow
        def call(operation,**arguments):
            reply=original(operation,**arguments)
            if operation=='workerPrepare':self.agent._command_queue.put('new input')
            return reply
        self.bridge.call_workflow=call
        with self.assertRaises(AutonomyPaused):self.service.deliver(result)
        self.assertEqual(self.publications,[]);self.assertEqual(len(self.store.pending_notifications('actual-owner')),1)

    def test_changed_saved_publication_reference_cannot_be_rebound_to_a_different_attempt(self):
        result=self.brain.pending_task_results()[0]['result'];saved=self.store.pending_notifications('actual-owner')[0]['prepared_result']
        saved['workflow_ref']['workerID']=self.other['task'].id
        self.store._connection.execute('UPDATE task_notifications SET result_json=? WHERE id=?',(json.dumps(saved),self.source['notification']));self.store._connection.commit()
        self.assertEqual(self.brain.pending_task_results(),[])
        self.assertEqual(self.publications,[]);self.assertEqual(self.brain._active_user_id,'unknown')

    def test_legacy_accepted_rows_do_not_create_new_publication_or_followup_on_upgrade(self):
        self.brain.pending_task_results();self.service.acknowledge(self.source['notification'],'actual-owner')
        self.grants[0]['managedResults']=[]
        self.assertFalse(self.service.due());self.service.retry_one()
        self.assertFalse(any(name=='workerPrepare' for name,args in self.calls))
        self.assertFalse(self.service.rows()[0]['followup_checked'])
    def test_later_native_delivered_source_waiting_for_ack_is_included_in_earlier_followup(self):
        later=self.seed('actual-owner',product_id=self.source['grant']['taskID']);self.grants.append(later['grant'])
        self.assertNotEqual(self.source['notification'],later['notification'])
        deliveries=self.brain.pending_task_results();self.assertEqual(len(deliveries),2)
        self.service.acknowledge(self.source['notification'],'actual-owner')
        payload=dict(id='task-continuation:'+'e'*64,**{key:self.source['grant'][key] for key in ('taskID','inputID','requirementsRevision','planVersion')},
            sourceOutcomeID='assessment:task-result:'+later['notification'],workerResultID='task-result:'+later['notification'],mode='work',context={})
        original=self.bridge.call_workflow
        def call(operation,**arguments):
            if operation=='workerFollowup':return dict(candidate=payload)
            return original(operation,**arguments)
        self.bridge.call_workflow=call;self.service.retry_one()
        saved=self.store.continuation(payload['id'],'actual-owner')['payload']
        self.assertEqual({row['resultID'] for row in saved['context']['deliveredResults']},{'task-result:'+self.source['notification'],'task-result:'+later['notification']})
        self.assertEqual(self.store.pending_continuations('actual-owner',self.bridge.session_id),[], 'Execution still waits for actual source notification ACK')
        self.assertEqual(self.publications,[])

    def test_negotiation_is_opt_in_and_requires_actual_resumption_and_worker_evidence(self):
        for value in (True,2,1):
            bridge=NativeRuntimeBridge(EventHub())
            try:
                with self.assertRaises(ValueError):bridge._dispatch('initialize',dict(workerResultVersion=value))
            finally:bridge.close()
        bridge=NativeRuntimeBridge(EventHub())
        try:self.assertEqual(bridge._dispatch('initialize',{})['workerResultVersion'],0)
        finally:bridge.close()


if __name__=='__main__':unittest.main()
