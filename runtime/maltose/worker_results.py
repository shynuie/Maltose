"""Task-scoped delivery of real worker attempts across independent questions.

A native grant names product/worker/attempt IDs, never a replacement principal.
The private store supplies the original owner only for those exact saved rows.
"""
from dataclasses import replace
import hashlib
import threading

from maltose.runtime.control import AutonomyPaused


class WorkerResultService:
    def __init__(self,bridge):self.bridge=bridge;self._local=threading.local()
    @property
    def store(self):return self.bridge.brain.task_manager.store
    def grants(self):
        brain=self.bridge.brain
        identity=getattr(brain,'_active_input_id',None)
        if not identity:return []
        try:return self.bridge.call_workflow('workerPending',inputID=identity).get('workers',[])
        except (RuntimeError,PermissionError,ValueError,ConnectionError,TimeoutError,AutonomyPaused):return []
    def rows(self,*,pending=False):return self.store.scoped_product_notifications(self.grants(),pending_only=pending)
    def managed(self,result):
        source=result.workflow_ref or {}
        return self.bridge.worker_result_version==1 and result.delivery_origin=='background' and bool(source.get('workerID') and source.get('attemptID'))
    def checked_result(self,row):
        result=self.bridge.brain._prepare_task_result(row,delivery_owner=row['user_id'])
        source=row['attempt_workflow'];reference=result.workflow_ref or {}
        expected={**source,'workerID':row['task_id'],'workerState':row['status'],'resultID':'task-result:'+row['notification_id'],
            'resultDigest':hashlib.sha256((row['result_summary'] or row['error'] or '').encode()).hexdigest()}
        if result.result_id!=expected['resultID'] or reference!=expected:raise ValueError('Saved worker publication changed its original attempt source')
        return result
    def pending(self,limit):
        values=[]
        for row in self.rows(pending=True):
            try:result=self.checked_result(row)
            except (ValueError,TypeError,KeyError):
                errors=self.bridge.brain.__dict__.setdefault('_notification_prepare_errors',set())
                if row['notification_id'] not in errors:
                    errors.add(row['notification_id']);self.bridge.hub.publish('result_preparation_failed',{'notification_id':row['notification_id']})
                continue
            values.append(dict(notification_id=row['notification_id'],result=result,recovered=row['recovered'],
                cancelled=row['status']=='cancelled',delivery_owner=row['user_id']))
            if len(values)>=limit:break
        return values
    def pending_ids(self):return [row['notification_id'] for row in self.rows(pending=True) if row['notification_id'] not in getattr(self.bridge.brain,'_notification_prepare_errors',set())]
    def owner(self,reference):
        rows=[row for row in self.rows() if all((row.get('attempt_workflow') or {}).get(key)==reference.get(key) for key in ('taskID','inputID','requirementsRevision','planVersion'))]
        owners={row['user_id'] for row in rows}
        if len(owners)!=1:raise AutonomyPaused('The native task scope no longer identifies a worker result owner')
        return next(iter(owners))
    def trigger(self,reference,publication_id):
        for row in self.rows():
            if 'task-result:'+row['notification_id']==publication_id and all((row.get('attempt_workflow') or {}).get(key)==reference.get(key) for key in ('taskID','inputID','requirementsRevision','planVersion')):
                return row
        raise PermissionError('No actual worker notification matches the native continuation root')
    def acknowledge(self,identity,owner):
        if not any(row['notification_id']==identity and row['user_id']==owner for row in self.rows()):raise AutonomyPaused('Worker delivery grant expired before ACK')
        self.store.acknowledge_notification(identity,owner)
        return self.store.claim_notification_speech(identity,owner)
    def metadata(self,result):
        reference=result.workflow_ref
        return dict(publicationID=result.result_id,**{key:reference[key] for key in ('taskID','inputID','workerID','attemptID','requirementsRevision','planVersion','resultDigest','workerState')},
            title=result.title,markdownSHA256=hashlib.sha256(result.display_text.encode()).hexdigest(),createDocument=result.needs_document,
            chart=result.chart.to_dict() if result.chart and self.bridge.result_chart_version==1 else None,deliverySessionID=self.bridge.session_id,state='prepared')
    def checkpoint(self):
        check=getattr(self._local,'check',None)
        if check:check()
        else:
            self.bridge.control.checkpoint()
            agent=self.bridge.agent
            if not agent._command_queue.empty() or agent._shutdown_requested.is_set():raise AutonomyPaused('A human input superseded worker followup')
    def deliver(self,result):
        brain,agent=self.bridge.brain,self.bridge.agent
        principal=(getattr(brain,'_active_user_id',None),getattr(brain,'_active_speaker_status',None))
        with agent._output_lock:generation=agent._output_generation
        epoch=self.bridge.control.epoch
        def check():
            self.bridge.control.checkpoint(expected_epoch=epoch)
            with agent._output_lock:fresh=generation==agent._output_generation
            if not fresh or principal!=(getattr(brain,'_active_user_id',None),getattr(brain,'_active_speaker_status',None)) or not agent._command_queue.empty() or agent._shutdown_requested.is_set():
                raise AutonomyPaused('New input superseded worker delivery')
        previous=getattr(self._local,'check',None);self._local.check=check
        try:
            check();self.owner(result.workflow_ref)
            prepared=self.bridge.call_workflow('workerPrepare',inputID=result.workflow_ref['inputID'],workerPublication=self.metadata(result),
                observations=self.bridge.workflow.worker_observations(result.workflow_ref))
            if prepared.get('deferred') is True:return dict(chatStored=False,workflowStored=False,status='worker_deferred')
            reference=dict(result.workflow_ref)
            if prepared.get('resumeAfterID'):reference['resumeAfterID']=prepared['resumeAfterID']
            scoped=replace(result,workflow_ref=reference)
            check();return self.bridge._present_result(scoped)
        finally:self._local.check=previous
    def mark_delivered(self,result):
        self.checkpoint()
        self.bridge.call_workflow('workerDelivered',inputID=result.workflow_ref['inputID'],workerPublication=self.metadata(result))
    def prepare_assessment(self,result):
        self.checkpoint()
        self.bridge.call_workflow('workerAssessment',inputID=result.workflow_ref['inputID'],workerPublication=self.metadata(result))
    def due(self):
        return any(row['delivery_status']=='accepted' and row['native_managed'] and not row['followup_checked'] and row['prepared_result'] is not None for row in self.rows())
    def retry_one(self):
        row=next((row for row in self.rows() if row['delivery_status']=='accepted' and row['native_managed'] and not row['followup_checked'] and row['prepared_result'] is not None),None)
        if row is None:return
        # Renew only delivery authority. Read back the exact already-saved body;
        # do not replay worker execution or claim another human identity.
        try:
            result=self.checked_result(row)
            self.checkpoint()
            prepared=self.bridge.call_workflow('workerPrepare',inputID=result.workflow_ref['inputID'],workerPublication=self.metadata(result),
                observations=self.bridge.workflow.worker_observations(result.workflow_ref))
            if prepared.get('deferred') is True:return
            self.mark_delivered(result)
            response=self.bridge.call_workflow('workerFollowup',inputID=result.workflow_ref['inputID'],workerPublication=self.metadata(result))
            payload=response.get('candidate')
            if payload:
                root=self.trigger(payload,payload['workerResultID']);owner=root['user_id']
                delivered=self.store.delivered_product_results(owner,payload)
                if not delivered['complete']:return
                previous=delivered['results']
                if not any(value['resultID']==payload['workerResultID'] for value in previous):
                    value=self.checked_result(root)
                    previous.append(dict(resultID=value.result_id,full_text=value.display_text,limitations=list(value.limitations),chatStored=True))
                payload['context']['deliveredResults']=previous
                self.store.enqueue_continuation(owner,root['notification_id'],payload)
            self.store.mark_worker_followup(row['notification_id'],row['user_id'])
        except (RuntimeError,ValueError,PermissionError,ConnectionError,TimeoutError,AutonomyPaused):
            return  # Durable followup stays pending; no work is repeated.
