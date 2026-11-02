"""Durable foreground answers, scoped to a real human input, never a Memory owner.

Preparation runs after generation and before final publication. Recovery only
replays the saved body/review; it cannot enter the task/tool loop or restore a
speaker identity. The native writer independently validates source and freshness.
"""
from dataclasses import replace
import hashlib
import time
import logging

logger = logging.getLogger(__name__)

from maltose.presentation import AnswerResult
from maltose.runtime.control import AutonomyPaused


class ForegroundResultService:
    def __init__(self, bridge):
        self.bridge = bridge
        self.retry_after = {}
        self.reported_errors = {}
        from maltose.visual_planning import VisualPlanningService
        self.visuals = VisualPlanningService(self)

    @property
    def store(self): return self.bridge.brain.task_manager.store

    @property
    def conversation_id(self):
        if not self.bridge.conversation_id: raise ValueError('Foreground delivery requires a saved conversation')
        return self.bridge.conversation_id

    def prepare(self, result, *, context=None, user_text=""):
        brain = self.bridge.brain
        input_id = getattr(brain, '_active_input_id', None)
        if not input_id or (getattr(context, 'input_id', input_id) not in (None, input_id)):
            raise ValueError('Foreground delivery requires the actual input source')
        if (result.workflow_ref or {}).get('foregroundID'):
            saved = self.store.foreground_result(result.result_id, self.conversation_id)
            effective=self.visuals.effective(result.result_id)
            if result not in (AnswerResult.from_record(saved['payload']['result']),effective): raise ValueError('Foreground content changed')
            resolved=self.visuals.resolve(result.result_id)
            if resolved is None:raise AutonomyPaused('Saved answer awaits current presentation scope')
            return resolved
        reference = getattr(brain, '_active_workflow_ref', None)
        if reference:
            if reference.get('inputID') != input_id: raise ValueError('Foreground task source changed')
            reference = {key: reference[key] for key in ('taskID', 'inputID', 'requirementsRevision', 'planVersion')}
        identity = 'main-result:' + hashlib.sha256((self.conversation_id + '\0' + input_id + '\0' + result.result_id).encode()).hexdigest()[:32]
        result = replace(result, result_id=identity, workflow_ref={**(reference or {}), 'foregroundID': identity})
        payload = dict(result=result.to_record(), inputID=input_id, reference=reference,
            producerSessionID=self.bridge.session_id,
            principal=dict(userID=getattr(context, 'user_id', None), status=getattr(context, 'speaker_status', None),
                           source=getattr(context, 'input_source', None)),
            observations=self.bridge.workflow.observations(reference))
        self.store.prepare_foreground_result(self.conversation_id, payload)
        self.visuals.queue(identity,result,user_text,payload['observations'])
        resolved=self.visuals.resolve(identity)
        if resolved is None:raise AutonomyPaused('Saved answer awaits current presentation scope')
        return resolved

    def source(self, payload, result):
        source = dict(publicationID=result.result_id, inputID=payload['inputID'],
            messageID=result.chat_message_id or result.result_id, title=result.title,
            markdownSHA256=hashlib.sha256(result.display_text.encode()).hexdigest(), createDocument=result.needs_document,
            producerSessionID=payload['producerSessionID'], deliverySessionID=self.bridge.session_id, state='prepared')
        if result.chart and getattr(self.bridge, 'result_chart_version', 0) == 1: source['chart'] = result.chart.to_dict()
        if payload['reference']:
            source.update({key: value for key, value in payload['reference'].items() if key != 'inputID'})
        return source

    def due(self):
        return any(time.monotonic() >= self.retry_after.get(row['id'], 0)
                   for row in self.store.pending_foreground_results(self.conversation_id)) or bool(getattr(self.bridge,'foreground_continuation_version',0)==1 and any(time.monotonic() >= self.retry_after.get(row['id'],0) for row in self.store.pending_foreground_followups(self.conversation_id)))

    def deliver(self, identity, *, retry=False):
        bridge = self.bridge
        row = self.store.foreground_result(identity, self.conversation_id)
        if row['phase'] != 'pending':
            return dict(chatStored=row['phase'] == 'delivered', workflowStored=True, foregroundSpeechAllowed=False,
                        status='replayed' if row['phase'] == 'delivered' else 'superseded')
        payload = row['payload']
        receipt = dict(chatStored=False, workflowStored=False, foregroundSpeechAllowed=False, status='delivery_pending')
        try:
            result=self.visuals.resolve(identity)
            if result is None:return receipt
            source=self.source(payload,result)
            prepared = bridge.call_workflow('foregroundPrepare', inputID=payload['inputID'], foregroundPublication=source,
                answerKind=result.kind, answerSummary=result.spoken_summary or result.title, observations=payload['observations'])
            if prepared.get('current') is not True:
                if prepared.get('superseded') is not True: return receipt
                self.store.finish_foreground_result(identity, self.conversation_id, superseded=True)
                return {**receipt, 'workflowStored': True, 'status': 'superseded'}
            receipt.update(bridge._deliver_result(result))
            if receipt.get('chatStored') is not True: return receipt
            report = bridge.call_workflow('foregroundDelivered', inputID=payload['inputID'], resultID=identity)
            reference = payload['reference']
            context = report.get('assessmentContext', {})
            if not isinstance(context, dict): raise ValueError('Invalid foreground assessment context')
            if context.get('stale'):
                self.store.finish_foreground_result(identity, self.conversation_id)
                return {**receipt, 'workflowStored': True, 'foregroundSpeechAllowed': False}
            assessment = report.get('assessment')
            if reference and assessment is None:
                if not context or not isinstance(context, dict): raise ValueError('Missing foreground assessment context')
                proposal = row['assessment']
                if proposal is None:
                    from maltose.workflow_verification import assess_result
                    proposal = assess_result(bridge.brain, context, result, allow_partial=getattr(bridge,'foreground_continuation_version',0)==1) if context else None
                    if proposal is not None:
                        # Save the tool-free model output BEFORE submitting it to the host.
                        self.store.save_foreground_assessment(identity, self.conversation_id, proposal)
                if proposal is not None:
                    assessment = bridge.call_workflow('assessResult', **reference, resultID=identity, assessment=proposal).get('assessment')
            if assessment:
                body = '任務核對：' + assessment['summary']
                if assessment.get('remaining'): body += '\n\n尚待處理：\n' + '\n'.join('• ' + item for item in assessment['remaining'])
                metadata = {**source, 'assessment': dict(title='任務核對', markdownSHA256=hashlib.sha256(body.encode()).hexdigest())}
                bridge.call_workflow('foregroundAssessment', inputID=payload['inputID'], resultID=identity, foregroundPublication=metadata)
                assessment_result = AnswerResult(body, '', title='任務核對', visual='none', result_id=identity + ':assessment',
                    chat_message_id=identity + ':assessment')
                if bridge._deliver_result(assessment_result).get('chatStored') is not True: return receipt
                receipt['workflowAssessment'] = assessment
            self.store.finish_foreground_result(identity, self.conversation_id)
            if getattr(bridge,'foreground_continuation_version',0)==1:
                try: bridge.continuations.enqueue_foreground(result,result.workflow_ref)
                except (ValueError,RuntimeError,PermissionError,ConnectionError,TimeoutError,AutonomyPaused): pass  # Durable followup_checked=0 is retried below.
            claimed = self.store.claim_foreground_speech(identity, self.conversation_id)
            receipt.update(workflowStored=True, foregroundSpeechAllowed=claimed and not retry and payload['producerSessionID'] == bridge.session_id)
            return receipt
        except (RuntimeError, ValueError, PermissionError, ConnectionError, TimeoutError, AutonomyPaused) as error:
            # A native save may have succeeded. Retry exactly this saved publication,
            # using a host check, never another task invocation or another panel ID.
            label = type(error).__name__
            if self.reported_errors.get(identity) != label:
                logger.warning('foreground_delivery_pending result_id=%s error=%s', identity, label, exc_info=True)
                self.reported_errors[identity] = label
            return {**receipt, 'deliveryError': label}
        finally:
            self.retry_after[identity] = time.monotonic() + 5

    def retry_one(self):
        row = next((row for row in self.store.pending_foreground_results(self.conversation_id)
                    if time.monotonic() >= self.retry_after.get(row['id'], 0)), None)
        if row is None:
            if getattr(self.bridge,'foreground_continuation_version',0)==1:
                row=next((v for v in self.store.pending_foreground_followups(self.conversation_id) if time.monotonic() >= self.retry_after.get(v['id'],0)),None)
                if row:
                    try:
                        result=self.visuals.effective(row['id'])
                        self.bridge.continuations.enqueue_foreground(result,result.workflow_ref)
                    except (ValueError,RuntimeError,PermissionError,ConnectionError,TimeoutError,AutonomyPaused): self.retry_after[row['id']]=time.monotonic()+5
            return
        receipt = self.deliver(row['id'], retry=True)
        if receipt.get('chatStored') is True and receipt.get('workflowStored') is True:
            result = self.visuals.effective(row['id'])
            self.bridge.agent._publish('assistant_message', dict(message_id=result.chat_message_id or result.result_id,
                content=result.display_text, source='maltose-foreground-recovery'))
