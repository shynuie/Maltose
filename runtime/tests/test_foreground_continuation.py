"""Real foreground FK/SQLite and one shared TaskBrain continuation engine."""
import io
from dataclasses import replace
import json
from pathlib import Path
from types import SimpleNamespace
import tempfile
import unittest
import uuid

from maltose.agent import TaskBrain,TaskStore,MemoryStore,VoiceAgent,AgentConfig
from maltose.presentation import AnswerResult
from maltose.foreground_results import ForegroundResultService
from maltose.product_continuation import ProductContinuationService
from maltose.runtime.control import AutonomyControl
from maltose.runtime import EventHub
from maltose.ui.native import NativeRuntimeBridge
from maltose.ui.workflow import NativeWorkflowToolAdapter


class ForegroundContinuationTests(unittest.TestCase):
    def setup_source(self, directory, *, session='first'):
        store=TaskStore(Path(directory)/'tasks.sqlite3'); self.addCleanup(store.close)
        brain=TaskBrain(SimpleNamespace(),memory=MemoryStore(Path(directory)/'memory.json'))
        brain.task_manager=SimpleNamespace(store=store); brain._active_user_id=None; brain._active_speaker_status='unknown'
        brain._active_input_id='human'; brain._active_workflow_ref=dict(taskID=str(uuid.uuid4()),inputID='human',requirementsRevision=1,planVersion=1)
        control=AutonomyControl()
        agent=VoiceAgent(config=AgentConfig(speech_mode='mute'),brain=brain,control_gate=control,voice_enabled=False)
        bridge=SimpleNamespace(brain=brain,agent=agent,control=control,conversation_id='conversation',session_id=session,
            foreground_continuation_version=1,result_chart_version=1,workflow=SimpleNamespace(observations=lambda ref:[]))
        result=ForegroundResultService(bridge).prepare(AnswerResult('第一份完整資料：17。','第一份有17。',kind='partial'))
        store.finish_foreground_result(result.result_id,'conversation')
        payload=dict(id='task-continuation:'+'a'*64,foregroundID=result.result_id,**brain._active_workflow_ref,
                     sourceOutcomeID=result.result_id,mode='work',inputSource='native',context=dict(criteria=['綜整兩份資料'],deliveredResults=[]))
        service=ProductContinuationService(bridge); state=dict(valid=True,complete=False,fail=False,model=0,tools=0,operations=[],publications={})
        def call(operation,**arguments):
            state['operations'].append(operation)
            if operation=='continuationContext':return dict(candidate=None if state['complete'] else json.loads(json.dumps(payload)))
            if not state['valid']:raise RuntimeError('new input or stopped authority')
            return dict(mode='work',valid=True)
        def present(value):
            state['publications'].setdefault(value.result_id,value)
            if state['fail']:return dict(chatStored=False,workflowStored=False)
            state['complete']=True
            return dict(chatStored=True,workflowStored=True,workflowAssessment=dict(status='completed',summary='兩份資料已綜整。'))
        bridge.call_workflow=call;bridge.present_result=present
        def model(messages,tools):
            state['model']+=1
            return {'choices':[{'message':{'content':json.dumps(dict(schemaVersion=1,title='綜整',full_text='第一份17，第二份34，合計51。',spoken_summary='合計51。',kind='answer',visual='document',limitations=[]),ensure_ascii=False)}}]}
        brain.model=SimpleNamespace(complete=model)
        return store,brain,bridge,service,result,payload,state

    def test_real_foreground_trigger_needs_no_user_or_fake_worker_and_keeps_sources_isolated(self):
        with tempfile.TemporaryDirectory() as directory:
            store,brain,bridge,service,result,payload,state=self.setup_source(directory)
            self.assertTrue(service.enqueue_foreground(result,result.workflow_ref))
            self.assertTrue(service.due()); service.run_one()
            self.assertEqual(state['model'],1)
            self.assertEqual(store.foreground_continuation(payload['id'],'conversation')['phase'],'delivered')
            self.assertEqual(store._connection.execute('select count(*) from tasks').fetchone()[0],0)
            self.assertEqual(store._connection.execute('select count(*) from task_notifications').fetchone()[0],0)
            self.assertEqual(store._connection.execute('select count(*) from product_continuations').fetchone()[0],0)
            self.assertIsNone(brain._active_user_id);self.assertFalse(brain._identity_is_known())
            with self.assertRaises(KeyError):store.foreground_continuation(payload['id'],'another')
            with self.assertRaises(ValueError):store.enqueue_foreground_continuation('conversation',result.result_id,{**payload,'inputID':'forged'})
            delivered=store.delivered_foreground_results('conversation',result.result_id)
            self.assertTrue(delivered['complete']);self.assertEqual(len(delivered['results']),2)
            self.assertIn('17',delivered['results'][0]['full_text']);self.assertIn('51',delivered['results'][1]['full_text'])

    def test_generated_recovery_only_replays_saved_output_and_never_promotes_identity(self):
        with tempfile.TemporaryDirectory() as directory:
            store,brain,bridge,service,result,payload,state=self.setup_source(directory)
            service.enqueue_foreground(result,result.workflow_ref);state['fail']=True;service.run_one()
            self.assertEqual(store.foreground_continuation(payload['id'],'conversation')['phase'],'generated')
            store.close();reopened=TaskStore(Path(directory)/'tasks.sqlite3');self.addCleanup(reopened.close)
            brain.task_manager.store=reopened;bridge.session_id='second';state['fail']=False
            recovered=ProductContinuationService(bridge);recovered.run_one()
            self.assertEqual(state['model'],1);self.assertEqual(len(state['publications']),1)
            self.assertEqual(reopened.foreground_continuation(payload['id'],'conversation')['phase'],'delivered')
            self.assertIsNone(bridge.agent._last_result);self.assertIsNone(brain._active_user_id)

    def test_running_recovery_stays_uncertain_and_commits_without_reentering_model(self):
        with tempfile.TemporaryDirectory() as directory:
            store,brain,bridge,service,result,payload,state=self.setup_source(directory)
            service.enqueue_foreground(result,result.workflow_ref)
            store.update_foreground_continuation(payload['id'],'conversation','running',session_id='first')
            self.assertEqual(store.pending_foreground_continuations('conversation','second'),[])
            store.close();reopened=TaskStore(Path(directory)/'tasks.sqlite3');self.addCleanup(reopened.close)
            self.assertEqual(reopened.foreground_continuation(payload['id'],'conversation')['phase'],'uncertain')
            brain.task_manager.store=reopened;bridge.session_id='second';ProductContinuationService(bridge).run_one()
            self.assertEqual(state['model'],0)

    def test_new_input_before_work_blocks_model_and_preserves_original_source(self):
        with tempfile.TemporaryDirectory() as directory:
            store,brain,bridge,service,result,payload,state=self.setup_source(directory)
            service.enqueue_foreground(result,result.workflow_ref);state['valid']=False;service.run_one()
            self.assertEqual(state['model'],0);self.assertEqual(state['publications'],{})
            self.assertEqual(store.foreground_continuation(payload['id'],'conversation')['phase'],'interrupted')
            self.assertEqual(store.foreground_result(result.result_id,'conversation')['phase'],'delivered')

    def test_parent_delivery_and_context_are_immutable_and_scoped_to_real_root(self):
        with tempfile.TemporaryDirectory() as directory:
            store,brain,bridge,service,result,payload,state=self.setup_source(directory)
            service.enqueue_foreground(result,result.workflow_ref)
            changed={**payload,'context':{'changed':'context'}}
            with self.assertRaises(ValueError):store.enqueue_foreground_continuation('conversation',result.result_id,changed)
            child={**payload,'id':'task-continuation:'+'b'*64,'sourceOutcomeID':payload['id']}
            with self.assertRaises(ValueError):store.enqueue_foreground_continuation('conversation',result.result_id,child,parent_id=payload['id'])
            self.assertFalse((Path(directory)/'memory.json').exists())

    def resumption(self, directory):
        store,brain,bridge,service,result,payload,state=self.setup_source(directory)
        brain._active_input_id='independent';brain._active_workflow_ref=None
        answer=ForegroundResultService(bridge).prepare(AnswerResult('獨立問題的答案是5。','答案是5。'))
        bridge.task_resumption_version=1
        payload.update(id='task-continuation:'+'c'*64,resumeAfterID=answer.result_id)
        original=bridge.call_workflow
        def call(operation,**args):
            if operation=='resumeContext':
                self.assertEqual(args,dict(inputID='independent',resultID=answer.result_id))
                return dict(candidate=json.loads(json.dumps(payload)))
            return original(operation,**args)
        bridge.call_workflow=call
        return store,brain,bridge,service,result,payload,state,answer

    def test_independent_answer_resumes_original_source_only_after_delivery_without_new_requirement_or_owner(self):
        with tempfile.TemporaryDirectory() as directory:
            store,brain,bridge,service,result,payload,state,answer=self.resumption(directory)
            with self.assertRaises(ValueError):service.enqueue_foreground(answer,answer.workflow_ref)
            self.assertEqual(state['model'],0)
            store.finish_foreground_result(answer.result_id,'conversation')
            self.assertFalse(service.enqueue_resumption(replace(answer,format_issue='invalid_result_format'),store.foreground_result(answer.result_id,'conversation')))
            self.assertTrue(service.enqueue_foreground(answer,answer.workflow_ref));service.run_one()
            row=store.foreground_continuation(payload['id'],'conversation')
            self.assertEqual(row['phase'],'delivered');self.assertEqual(row['payload']['inputID'],'human')
            self.assertEqual(row['result']['workflow_ref']['resumeAfterID'],answer.result_id)
            self.assertEqual(brain._active_input_id,'independent');self.assertIsNone(brain._active_user_id)
            self.assertEqual(store._connection.execute('select count(*) from tasks').fetchone()[0],0)
            self.assertEqual(store.foreground_result(result.result_id,'conversation')['payload']['inputID'],'human')
            self.assertEqual(state['model'],1)

    def test_resumption_rejects_changed_answer_source_and_recovers_generated_delivery_without_reexecuting(self):
        with tempfile.TemporaryDirectory() as directory:
            store,brain,bridge,service,result,payload,state,answer=self.resumption(directory)
            store.finish_foreground_result(answer.result_id,'conversation')
            payload['resumeAfterID']='main-result:'+'f'*32
            with self.assertRaises(ValueError):service.enqueue_foreground(answer,answer.workflow_ref)
            payload['resumeAfterID']=answer.result_id
            service.enqueue_foreground(answer,answer.workflow_ref);state['fail']=True;service.run_one()
            self.assertEqual(store.foreground_continuation(payload['id'],'conversation')['phase'],'generated')
            store.close();reopened=TaskStore(Path(directory)/'tasks.sqlite3');self.addCleanup(reopened.close)
            brain.task_manager.store=reopened;bridge.session_id='second';state['fail']=False
            ProductContinuationService(bridge).run_one()
            self.assertEqual(state['model'],1);self.assertEqual(reopened.foreground_continuation(payload['id'],'conversation')['phase'],'delivered')
            self.assertIsNone(bridge.agent._last_result)

    def test_resumption_capability_is_independent_and_requires_foreground_continuations(self):
        base=dict(presentationVersion=1,resultDeliveryVersion=1,workflowVersion=1,inputScopeVersion=1,foregroundResultVersion=1,
                  workerEvidenceVersion=1,continuationVersion=1,foregroundContinuationVersion=1,taskResumptionVersion=1,conversationID='conversation')
        for change in ({'taskResumptionVersion':True},{'foregroundContinuationVersion':0}):
            bridge=NativeRuntimeBridge(EventHub(),output_stream=io.StringIO());self.addCleanup(bridge.close)
            with self.assertRaises(ValueError):bridge._dispatch('initialize',{**base,**change})
        bridge=NativeRuntimeBridge(EventHub(),output_stream=io.StringIO());self.addCleanup(bridge.close)
        self.assertEqual(bridge._dispatch('initialize',base)['taskResumptionVersion'],1)
        older=NativeRuntimeBridge(EventHub(),output_stream=io.StringIO());self.addCleanup(older.close)
        base.pop('taskResumptionVersion')
        self.assertEqual(older._dispatch('initialize',base)['taskResumptionVersion'],0)

    def test_only_known_read_errors_reach_model_as_failed_receipts_and_never_become_source_proof(self):
        from maltose.agent.taskbrain import ToolRegistry
        from maltose.tool_observations import collect_tool_returns
        registry=ToolRegistry()
        def missing(args):raise FileNotFoundError('unavailable')
        registry.register('read_file','read',{},missing)
        registry.register('write_file','write',{},missing)
        with self.assertRaises(FileNotFoundError):registry.execute('read_file',{})
        with collect_tool_returns() as receipts:
            result=registry.execute('read_file',{},report_read_errors=True)
        self.assertEqual(result['status'],'failed');self.assertTrue(result['outcomeKnown'])
        self.assertEqual(len(receipts),1);self.assertNotIn('text',receipts[0]['result'])
        with self.assertRaises(FileNotFoundError):registry.execute('write_file',{},report_read_errors=True)
        def denied(args):raise PermissionError('approval is required')
        registry.register('private_read','read',{},denied)
        with self.assertRaises(PermissionError):registry.execute('private_read',{},report_read_errors=True)

    def test_new_capability_requires_foreground_delivery_and_existing_continuation_protocol(self):
        base=dict(presentationVersion=1,resultDeliveryVersion=1,workflowVersion=1,inputScopeVersion=1,foregroundResultVersion=1,
                  workerEvidenceVersion=1,continuationVersion=1,foregroundContinuationVersion=1,conversationID='conversation')
        for change in ({'foregroundContinuationVersion':True},{'foregroundResultVersion':0},{'continuationVersion':0}):
            bridge=NativeRuntimeBridge(EventHub(),output_stream=io.StringIO());self.addCleanup(bridge.close)
            with self.assertRaises(ValueError):bridge._dispatch('initialize',{**base,**change})
        bridge=NativeRuntimeBridge(EventHub(),output_stream=io.StringIO());self.addCleanup(bridge.close)
        self.assertEqual(bridge._dispatch('initialize',base)['foregroundContinuationVersion'],1)


if __name__=='__main__':unittest.main()
