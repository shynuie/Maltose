"""Main-loop continuation of a saved task, separate from human input routing."""
from dataclasses import replace
import time

from maltose.presentation import AnswerResult, SpeechPolicy, with_assessment
from maltose.runtime.control import AutonomyPaused


class ProductContinuationService:
    def __init__(self, bridge):
        self.bridge = bridge
        self.retry_after = {}

    @property
    def store(self): return self.bridge.brain.task_manager.store

    def owner(self):
        brain = self.bridge.brain
        return brain._active_user_id if callable(getattr(brain,'_identity_is_known',None)) and brain._identity_is_known() else None

    def reference(self, payload):
        value = {**{key: payload[key] for key in ('taskID', 'inputID', 'requirementsRevision', 'planVersion')}, 'continuationID': payload['id']}
        if payload.get('foregroundID'): value['foregroundID'] = payload['foregroundID']
        if payload.get('resumeAfterID'): value['resumeAfterID'] = payload['resumeAfterID']
        return value

    def enqueue(self, result, reference):
        if reference.get('foregroundID'): return self.enqueue_foreground(result, reference)
        scoped=getattr(self.bridge,'worker_results',None)
        owner=scoped.owner(reference) if scoped else self.owner()
        if not owner: return False
        source = {key: reference[key] for key in ('taskID', 'inputID', 'requirementsRevision', 'planVersion')}
        if reference.get('resumeAfterID'):source['resumeAfterID']=reference['resumeAfterID']
        response = self.bridge.call_workflow('continuationContext', **source, resultID=result.result_id)
        payload = response.get('candidate')
        if not payload: return False
        delivered = self.store.delivered_product_results(owner, reference)
        if not delivered['complete']: return False
        previous = delivered['results']
        if not any(value['resultID'] == result.result_id for value in previous):
            previous.append(dict(resultID=result.result_id, full_text=result.full_text, limitations=list(result.limitations), chatStored=True))
        payload['context']['deliveredResults'] = previous
        trigger = self.store.continuation(reference['continuationID'], owner)['trigger_id'] if reference.get('continuationID') else result.result_id.removeprefix('task-result:')
        self.store.enqueue_continuation(owner, trigger, payload)
        return True

    def foreground_enabled(self):
        return getattr(self.bridge,'foreground_continuation_version',0)==1 and bool(self.bridge.conversation_id)

    def enqueue_foreground(self, result, reference):
        if not self.foreground_enabled(): return False
        conversation = self.bridge.conversation_id
        parent = reference.get('continuationID'); root_id = reference['foregroundID']
        def checked(): self.store.mark_foreground_followup(parent or root_id,conversation,continuation=bool(parent))
        if result.kind=='needs_input' or result.format_issue=='continuation_error': checked(); return False
        root = self.store.foreground_result(root_id,conversation)
        if not root['payload']['reference']:
            queued=self.enqueue_resumption(result, root)
            checked(); return queued
        source={key:reference[key] for key in ('taskID','inputID','requirementsRevision','planVersion')}
        response=self.bridge.call_workflow('continuationContext',**source,foregroundID=root_id,resultID=result.result_id,**({'resumeAfterID':reference['resumeAfterID']} if reference.get('resumeAfterID') else {}))
        payload=response.get('candidate')
        if not payload: checked(); return False
        if payload.get('foregroundID') != root_id: raise ValueError('Native continuation changed its foreground source')
        delivered=self.store.delivered_foreground_results(conversation,root_id)
        if not delivered['complete']: checked(); return False
        payload['context']['deliveredResults']=delivered['results']
        self.store.enqueue_foreground_continuation(conversation,root_id,payload,parent_id=parent)
        checked()
        return True

    def enqueue_resumption(self, result, answer):
        if getattr(self.bridge,'task_resumption_version',0)!=1 or result.kind!='answer' or result.format_issue: return False
        response=self.bridge.call_workflow('resumeContext',inputID=answer['payload']['inputID'],resultID=result.result_id)
        payload=response.get('candidate')
        if not payload:return False
        if payload.get('resumeAfterID')!=result.result_id:raise ValueError('Resumption changed its delivered answer source')
        if not payload.get('foregroundID'):
            scoped=getattr(self.bridge,'worker_results',None)
            if not scoped or not payload.get('workerResultID'):return False
            trigger=scoped.trigger(payload,payload['workerResultID']);owner=trigger['user_id']
            delivered=self.store.delivered_product_results(owner,payload)
            if not delivered['complete']:return False
            previous=delivered['results']
            if not any(value['resultID']==payload['workerResultID'] for value in previous):
                saved=trigger['prepared_result']
                if not saved:return False
                value=AnswerResult.from_record(saved)
                previous.append(dict(resultID=value.result_id,full_text=value.full_text,limitations=list(value.limitations),chatStored=True))
            payload['context']['deliveredResults']=previous
            self.store.enqueue_continuation(owner,trigger['notification_id'],payload)
            return True
        root_id=payload['foregroundID'];conversation=self.bridge.conversation_id
        delivered=self.store.delivered_foreground_results(conversation,root_id)
        if not delivered['complete']:return False
        payload['context']['deliveredResults']=delivered['results']
        source=payload['sourceOutcomeID'].removeprefix('assessment:')
        self.store.enqueue_foreground_continuation(conversation,root_id,payload,parent_id=None if source==root_id else source)
        return True

    def _rows(self):
        rows=[]
        if self.foreground_enabled():
            rows += [('foreground',self.bridge.conversation_id,row) for row in self.store.pending_foreground_continuations(self.bridge.conversation_id,self.bridge.session_id)]
        scoped=getattr(self.bridge,'worker_results',None)
        if scoped:
            grants=scoped.rows()
            for owner in set(row['user_id'] for row in grants):
                triggers=[row['notification_id'] for row in grants if row['user_id']==owner]
                rows += [('worker',owner,row) for row in self.store.pending_continuations(owner,self.bridge.session_id,trigger_ids=triggers)]
        else:
            owner=self.owner()
            if owner:rows += [('worker',owner,row) for row in self.store.pending_continuations(owner,self.bridge.session_id)]
        return rows

    def due(self):
        return any(time.monotonic() >= self.retry_after.get(row['id'],0) for kind,key,row in self._rows())

    def _row(self, identity, owner):
        kind,key=owner
        return self.store.foreground_continuation(identity,key) if kind=='foreground' else self.store.continuation(identity,key)

    def _update(self, identity, owner, phase, **values):
        kind,key=owner
        method=self.store.update_foreground_continuation if kind=='foreground' else self.store.update_continuation
        method(identity,key,phase,**values)

    def _claim_speech(self, identity, owner):
        kind,key=owner
        return self.store.claim_foreground_continuation_speech(identity,key) if kind=='foreground' else self.store.claim_continuation_speech(identity,key)

    def observations(self, reference):
        scoped=getattr(self.bridge,'worker_results',None)
        owner=('foreground',self.bridge.conversation_id) if reference.get('foregroundID') else ('worker',scoped.owner(reference) if scoped else self.owner())
        row=self._row(reference['continuationID'],owner)
        if any(row['payload'].get(key)!=reference.get(key) for key in ('taskID','inputID','requirementsRevision','planVersion','foregroundID','resumeAfterID')):
            raise ValueError('Continuation evidence source changed')
        return row['observations']

    def run_one(self):
        selected=next(((kind,key,row) for kind,key,row in self._rows() if time.monotonic() >= self.retry_after.get(row['id'],0)),None)
        if selected is None: return
        kind,key,row=selected; owner=(kind,key)
        bridge, brain, agent = self.bridge, self.bridge.brain, self.bridge.agent
        payload = row['payload']; reference = self.reference(payload); scratch = {'observations': row['observations']}
        if row['phase']=='delivered':
            try: self.enqueue_foreground(AnswerResult.from_record(row['result']),reference)
            except (ValueError,RuntimeError,PermissionError,ConnectionError,TimeoutError,AutonomyPaused): self.retry_after[row['id']]=time.monotonic()+5
            return
        principal=(getattr(brain,'_active_user_id',None),getattr(brain,'_active_speaker_status',None))
        with agent._output_lock: generation = agent._output_generation
        epoch = bridge.control.epoch
        def checkpoint(*, host=True):
            bridge.control.checkpoint(expected_epoch=epoch)
            with agent._output_lock: fresh = generation == agent._output_generation
            same_principal=principal==(getattr(brain,'_active_user_id',None),getattr(brain,'_active_speaker_status',None))
            if kind=='foreground':scope_valid=self.foreground_enabled() and bridge.conversation_id==key and same_principal
            else:scope_valid=same_principal if getattr(bridge,'worker_results',None) else self.owner()==key
            if not scope_valid or not fresh or not agent._command_queue.empty() or agent._shutdown_requested.is_set():
                raise AutonomyPaused('A newer human input or output generation superseded the continuation')
            if host:
                try: bridge.call_workflow('continuationCheck', **reference)
                except (RuntimeError, ValueError, PermissionError) as error:
                    raise AutonomyPaused('The saved continuation authority is no longer current') from error
        try:
            if row['phase'] != 'generated':
                checkpoint(host=False)
                self._update(row['id'], owner, 'admitting', session_id=bridge.session_id)
                try: admitted = bridge.call_workflow('continuationStart', **reference, sourceOutcomeID=payload['sourceOutcomeID'], **({'continuationPhase':'admitting'} if kind=='foreground' else {}))
                except (RuntimeError, ValueError, PermissionError) as error:
                    raise AutonomyPaused('Continuation admission is no longer valid') from error
                if admitted.get('deferred') is True:
                    self.retry_after[row['id']]=time.monotonic()+5
                    return
                if admitted.get('mode') != payload['mode']: raise ValueError('Continuation mode changed')
                self._update(row['id'], owner, 'running', session_id=bridge.session_id)
                try:
                    result = brain.continue_product_task(payload, checkpoint, scratch)
                except AutonomyPaused: raise
                except Exception:
                    result = AnswerResult('自動接續過程中斷。已取得的成果與操作紀錄保留；沒有自動重做可能已發生的操作，需先核對實際狀態。',
                        '接續中斷，已保留成果與紀錄，尚未重做操作。', kind='failed', visual='auto', result_id=row['id'], chat_message_id=row['id'], workflow_ref=reference, format_issue='continuation_error')
                self._update(row['id'], owner, 'generated', result=result.to_record(), observations=scratch['observations'])
                checkpoint()
            else:
                if row['recovered']:
                    admitted=bridge.call_workflow('continuationStart', **reference, sourceOutcomeID=payload['sourceOutcomeID'], **({'continuationPhase':'generated'} if kind=='foreground' else {}))
                    if admitted.get('deferred') is True:
                        self.retry_after[row['id']]=time.monotonic()+5
                        return
                result = AnswerResult.from_record(row['result'])
            checkpoint()
            receipt = bridge.present_result(result)
            if receipt.get('chatStored') is not True or receipt.get('workflowStored') is False:
                checkpoint()
                self.retry_after[row['id']] = time.monotonic() + 5
                return
            bridge.call_workflow('continuationACK', **reference)
            self._update(row['id'], owner, 'delivered')
            agent._publish('assistant_message', {'message_id': result.result_id, 'content': result.display_text, 'source': 'maltose-continuation'})
            if kind=='foreground':
                try: self.enqueue_foreground(result,reference)
                except (ValueError,RuntimeError,PermissionError,ConnectionError,TimeoutError,AutonomyPaused): self.retry_after[row['id']]=time.monotonic()+5
            may_speak = self._claim_speech(row['id'], owner)
            if not may_speak or row['recovered']: return
            assessment = receipt.get('workflowAssessment', {})
            result = with_assessment(result, assessment)
            source = payload.get('deliverySource',payload.get('inputSource', 'voice'))
            mode = 'mute' if agent._result_speech_muted else agent.config.speech_mode
            if mode not in {'mute', 'read'} and (mode == 'summary' or source not in {'native', 'web'}):
                result = brain.repair_spoken_summary(result, SpeechPolicy(target_seconds=agent.config.speech_target_seconds,
                    words_per_minute=agent.config.tts_rate or 175))
            agent._last_result = result; agent._last_result_scope = (principal[0] if kind=='foreground' or getattr(bridge,'worker_results',None) else key, brain._active_speaker_status, source)
            pending = agent._speak_result(result, source=source, mode=mode, generation=generation)
            if pending is not None and not pending.interrupt_requested:
                agent._pending_notification_turn = replace(pending, captured_epoch=epoch)
        except AutonomyPaused:
            if self._row(row['id'], owner)['phase'] == 'delivered': return
            self._interrupt(row, owner, reference, scratch)
        except (ValueError, RuntimeError, PermissionError, ConnectionError, TimeoutError):
            # Admission may have succeeded. Keep the same ID. Generated work is
            # never run again just because presentation/ACK failed.
            self.retry_after[row['id']] = time.monotonic() + 5

    def _interrupt(self, row, owner, reference, scratch):
        try: self.bridge.call_workflow('continuationAbort', **reference, observations=scratch['observations'])
        except (RuntimeError, ConnectionError, TimeoutError): pass
        try: self._update(row['id'], owner, 'interrupted', observations=scratch['observations'])
        except (RuntimeError, ValueError): pass
