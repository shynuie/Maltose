"""Versioned, private stdio bridge between the native app and the existing runtime.

Only the owning app holds the child's input pipe. Diagnostic output goes to stderr;
this module retains the original protocol stream. No network listener is opened.
"""
from __future__ import annotations

from collections import OrderedDict
import hashlib
import json
import os
import queue
import re
import sys
import threading
import time
import uuid
from typing import Any, TextIO

from maltose.runtime import EventHub
from maltose.runtime.control import AutonomyControl, AutonomyPaused
from maltose.codex.native_service import CONTROL_OWNER


class NativeRuntimeBridge:
    schema_version = 1
    maximum_line_bytes = 4 * 1024 * 1024

    def __init__(self, hub: EventHub, *, input_stream: TextIO | None = None,
                 output_stream: TextIO | None = None, collaboration=None, on_owner_lost=None) -> None:
        self.hub = hub
        self.on_owner_lost = on_owner_lost
        self.input = input_stream or sys.stdin
        self.output = output_stream or sys.__stdout__
        self.session_id = uuid.uuid4().hex
        self.agent = None
        self.brain = None
        self._initialized = threading.Event()
        self._closed = threading.Event()
        self._closing = threading.Event()
        self.control = AutonomyControl(self._publish_control)
        self.routing_enabled = False
        self.conversation_id = None
        self.collaboration = collaboration
        self._async_requests = {}
        self._voice_lock = threading.RLock()
        self._voice_scope = None
        self._voice_generation = 0
        self._voice_proofs = OrderedDict()
        self._close_lock = threading.Lock()
        self._graceful_shutdown = False
        self._shutdown_requested = threading.Event()
        self._write_lock = threading.Lock()
        self._request_lock = threading.Lock()
        self._sequence = 0
        self._ready = False
        self.tool_definitions: list[dict] = []
        self.presentation_version = 0
        self.result_delivery_version = 0
        self.result_chart_version = 0
        self.workflow_version = 0
        self.task_progress_version = 0
        self.worker_evidence_version = 0
        self.continuation_version = 0
        self.task_resumption_version = 0
        self.foreground_continuation_version = 0
        self.input_scope_version = 0
        self.visual_planning_version = 0
        self.panel_policy_version = 0
        self.panel_operation_version = 0
        self.public_web_source_version = 0
        self.worker_result_version=0
        self.foreground_result_version = 0
        self.file_service = None
        self.action_handler = None
        self._panel_lock = threading.Lock()
        self._panel_requests: dict[str, queue.Queue] = {}
        self._pending_panel_acknowledgements = {}
        self._requests: OrderedDict[str, tuple[str, dict]] = OrderedDict()
        self._subscription = hub.subscribe()
        self._threads: list[threading.Thread] = []

    def start(self) -> None:
        for target, name in [(self._read, 'maltose-native-input'), (self._events, 'maltose-native-events')]:
            thread = threading.Thread(target=target, name=name, daemon=True)
            self._threads.append(thread)
            thread.start()

    def wait_for_initialize(self, timeout: float = 30) -> None:
        if not self._initialized.wait(timeout):
            raise TimeoutError('Native app did not initialize the runtime connection')
        if self._closed.is_set():
            raise ConnectionError('Native app disconnected during initialization')

    def attach(self, agent: Any, brain: Any) -> None:
        existing = getattr(agent, 'control_gate', None)
        if existing is not None and existing is not self.control: raise RuntimeError('Agent is attached to another autonomy controller')
        if hasattr(agent, '_command_queue') and existing is None and agent.state.value != 'initializing':
            raise RuntimeError('Attach native control before starting the Agent')
        manager = getattr(brain, 'task_manager', None)
        if manager is not None and manager.control_gate is not self.control:
            raise RuntimeError('TaskManager must be initialized with the native autonomy controller')
        if getattr(brain, 'control_gate', None) not in (None, self.control):
            raise RuntimeError('Brain is attached to another autonomy controller')
        self.agent, self.brain = agent, brain
        agent.control_gate = self.control
        agent.input_router = self.route_input
        agent.voice_context_observer = self.observe_voice_context
        if self.workflow_version == 1: agent.input_observer = self.observe_workflow_input
        if brain is not None and hasattr(brain, 'tools'):
            brain.control_gate = self.control
            brain.tools.control_gate = self.control
            if self.collaboration: brain.collaboration_context = self.collaboration.last_observation
            if self.public_web_source_version == 1:
                from maltose.web_sources import PublicWebReader
                brain.install_public_web_reader(getattr(brain,'public_web_reader',None) or PublicWebReader())
            if self.workflow_version == 1:
                from maltose.ui.workflow import NativeWorkflowToolAdapter
                self.workflow = NativeWorkflowToolAdapter(self)
                brain.tools.result_observer = self.workflow.observe_tool_result
                if manager is not None and self.foreground_result_version == 1:
                    from maltose.foreground_results import ForegroundResultService
                    self.foreground = ForegroundResultService(self)
                    agent.result_preparer = self.foreground.prepare
                    agent.foreground_result_handler = self.foreground.retry_one
                    agent.foreground_result_due = self.foreground.due
                if manager is not None and self.worker_evidence_version == 1:
                    manager.attempt_observer = self.workflow.admit_worker_attempt
                    if self.continuation_version == 1:
                        from maltose.product_continuation import ProductContinuationService
                        self.continuations = ProductContinuationService(self)
                        agent.product_continuation_handler = self.continuations.run_one
                        agent.product_continuation_due = self.continuations.due
                    if self.worker_result_version==1:
                        from maltose.worker_results import WorkerResultService
                        self.worker_results=WorkerResultService(self)
                        brain.pending_worker_result_provider=self.worker_results.pending
                        brain.pending_worker_result_ids=self.worker_results.pending_ids
                        agent.result_publication_managed=self.worker_results.managed
                        agent.background_result_ack=self.worker_results.acknowledge
                        agent.worker_result_followup=self.worker_results.retry_one
                        agent.worker_result_followup_due=self.worker_results.due
        if self._shutdown_requested.is_set():
            agent.request_shutdown()

    def _publish_control(self, kind, payload):
        if not self._closing.is_set(): self.hub.publish(kind, payload)

    def observe_voice_context(self, context):
        with self._voice_lock:
            scope = (context.user_id, context.speaker_status)
            if scope != self._voice_scope:
                self._voice_proofs.clear()
                self._voice_scope = scope
                self._voice_generation += 1
            return self._voice_generation

    def route_input(self, text, context, source, captured_epoch, message_id):
        if source == 'voice': voice_generation = self.observe_voice_context(context)
        first_line = next((line for line in text.splitlines() if line.strip()), '')
        indented_code = first_line.startswith(('    ', '\t'))
        mention = re.match(r'^@(codex|maltose)(?=\s|[:：]|$)', text.strip(), re.IGNORECASE) if self.routing_enabled and not indented_code else None
        stale = captured_epoch is not None and captured_epoch != self.control.epoch
        if self.control.active and mention is None and not stale: return False
        payload = dict(messageID=message_id, content=text, source=source, runtimeSessionID=self.session_id,
            conversationID=self.conversation_id, controlOwnerID=self.control.snapshot()['ownerID'],
            recipient=mention.group(1).lower() if mention else 'maltose' if stale else 'current',
            deferred=stale and mention is None, capturedEpoch=captured_epoch,
            speaker=dict(userID=context.user_id, status=context.speaker_status, score=context.speaker_score))
        if self.collaboration: self.collaboration.save_input(payload)
        if source == 'voice' and not payload['deferred'] and context.speaker_status == 'identified' and context.user_id not in (None, '', 'unknown'):
            body = text.strip()
            if mention:
                body = body[mention.end():]
                if body.startswith((':', '：')): body = body[1:]
                body = body.strip()
            with self._voice_lock:
                if self._voice_generation == voice_generation:
                    self._voice_proofs[message_id] = (body, context, self._voice_scope, time.monotonic(),
                        mention.group(1).lower() if mention else None, voice_generation)
                while len(self._voice_proofs) > 256: self._voice_proofs.popitem(last=False)
        self.hub.publish('input_routed', payload)
        return True

    def _send(self, message: dict) -> None:
        with self._write_lock:
            if self._closed.is_set():
                return
            try:
                self.output.write(json.dumps({'schemaVersion': 1, **message}, ensure_ascii=False, allow_nan=False) + '\n')
                self.output.flush()
            except (BrokenPipeError, OSError, ValueError):
                if self.on_owner_lost is not None: self.on_owner_lost()
                self._shutdown_requested.set()
                if self.agent is not None:
                    self.agent.request_shutdown()
                self._closed.set()

    def _read(self) -> None:
        try:
            while not self._closed.is_set():
                line = self.input.readline(self.maximum_line_bytes + 1)
                if not line:
                    break
                self.receive_line(line)
        finally:
            if not self._graceful_shutdown and self.on_owner_lost is not None: self.on_owner_lost()
            self._shutdown_requested.set()
            if self.agent is not None:
                self.agent.request_shutdown()
            if not self._graceful_shutdown:
                self.close()

    def receive_line(self, line: str) -> None:
        request_id = None
        try:
            if len(line.encode('utf-8')) > self.maximum_line_bytes:
                raise ValueError('Native request exceeds size limit')
            request = json.loads(line)
            if not isinstance(request, dict):
                raise ValueError('Native request must be an object')
            if 'replyTo' in request:
                if request.get('schemaVersion') != 1 or request.get('sessionID') != self.session_id:
                    raise ValueError('Panel reply does not belong to this connection')
                with self._panel_lock:
                    response_queue = self._panel_requests.get(request['replyTo'])
                if response_queue is not None:
                    try: response_queue.put_nowait(request)
                    except queue.Full: pass
                return
            request_id = request.get('requestID')
            if not isinstance(request_id, str) or not request_id or len(request_id) > 128:
                raise ValueError('A bounded requestID is required')
            if request.get('schemaVersion') != self.schema_version:
                raise ValueError('Unsupported native protocol version')
            fingerprint = hashlib.sha256(json.dumps(request, sort_keys=True, ensure_ascii=False).encode()).hexdigest()
            with self._request_lock:
                previous = self._requests.get(request_id)
                if previous is not None:
                    if previous[0] != fingerprint:
                        raise ValueError('requestID was reused with different arguments')
                    self._send(previous[1])
                    return
                if request_id in self._async_requests:
                    if self._async_requests[request_id] != fingerprint: raise ValueError('In-flight requestID conflicts')
                    return
                if request.get('method') in {'workspace_prepare', 'workspace_inspect', 'workspace_changes', 'observe_codex', 'assess_codex', 'select_development_repository', 'execute_codex_panel', 'assess_panel_intent'}:
                    if len(self._async_requests) >= 16: raise RuntimeError('Too many collaboration operations')
                    self._async_requests[request_id] = fingerprint
                    # Non-daemon: process ownership persists until this controller operation
                    # completes, or the owning supervisor terminates the process group.
                    thread = threading.Thread(target=self._dispatch_async, args=(request_id, fingerprint, request),
                                              name='maltose-collaboration-operation')
                    thread.start()
                    return
                result = self._dispatch(request.get('method'), request.get('params', {}))
                response = {'requestID': request_id, 'sessionID': self.session_id, 'ok': True, 'result': result}
                self._requests[request_id] = (fingerprint, response)
                while len(self._requests) > 512:
                    self._requests.popitem(last=False)
                self._send(response)
                if request.get('method') == 'initialize':
                    self._initialized.set()
        except (ValueError, TypeError, KeyError, RuntimeError, PermissionError) as error:
            self._send({'requestID': request_id, 'sessionID': self.session_id, 'ok': False,
                        'error': {'code': 'invalid_state' if isinstance(error, RuntimeError) else 'invalid_request',
                                  'message': str(error)}})

    def _dispatch_async(self, identity, fingerprint, request):
        try:
            result = self._dispatch(request.get('method'), request.get('params', {}))
            response = dict(requestID=identity, sessionID=self.session_id, ok=True, result=result)
        except Exception as error:
            response = dict(requestID=identity, sessionID=self.session_id, ok=False,
                            error={'code': 'collaboration_failed', 'message': str(error)})
        with self._request_lock:
            self._async_requests.pop(identity, None)
            self._requests[identity] = (fingerprint, response)
            while len(self._requests) > 512: self._requests.popitem(last=False)
        self._send(response)

    def _require_controller(self, params):
        state = self.control.snapshot()
        if state['state'] != 'paused' or params.get('ownerID') != state['ownerID'] or params.get('leaseID') != state['leaseID']:
            raise PermissionError('Collaboration requires the current paused control lease')
        if self.collaboration is None: raise RuntimeError('Collaboration services are unavailable')

    def _dispatch(self, method: Any, params: Any) -> dict:
        if not isinstance(params, dict):
            raise ValueError('params must be an object')
        if method == 'initialize':
            if self._initialized.is_set(): raise RuntimeError('Native connection was already initialized')
            tools = params.get('tools', [])
            if not isinstance(tools, list) or any(not isinstance(tool, dict) for tool in tools):
                raise ValueError('Native tools must be an array of definitions')
            version = params.get('presentationVersion', 0)
            if type(version) is not int or version not in (0, 1): raise ValueError('Unsupported presentation version')
            delivery_version = params.get('resultDeliveryVersion', 0)
            if type(delivery_version) is not int or delivery_version not in (0, 1) or (delivery_version and version != 1):
                raise ValueError('Unsupported result delivery version')
            chart_version = params.get('resultChartVersion', 0)
            if type(chart_version) is not int or chart_version not in (0, 1) or chart_version and delivery_version != 1:
                raise ValueError('Unsupported result chart version')
            self.result_chart_version = chart_version
            workflow_version = params.get('workflowVersion', 0)
            if type(workflow_version) is not int or workflow_version not in (0, 1): raise ValueError('Unsupported workflow version')
            progress_version = params.get('taskProgressVersion', 0)
            if type(progress_version) is not int or progress_version not in (0, 1) or progress_version and workflow_version != 1:
                raise ValueError('Unsupported task progress version')
            self.task_progress_version = progress_version
            input_scope_version = params.get('inputScopeVersion', 0)
            if type(input_scope_version) is not int or input_scope_version not in (0, 1) or input_scope_version and workflow_version != 1:
                raise ValueError('Unsupported input scope version')
            foreground_version = params.get('foregroundResultVersion', 0)
            if type(foreground_version) is not int or foreground_version not in (0, 1) or foreground_version and (workflow_version != 1 or input_scope_version != 1 or delivery_version != 1):
                raise ValueError('Unsupported foreground result version')
            worker_version = params.get('workerEvidenceVersion', 0)
            if type(worker_version) is not int or worker_version not in (0, 1) or worker_version and workflow_version != 1: raise ValueError('Unsupported worker evidence version')
            continuation_version = params.get('continuationVersion', 0)
            if type(continuation_version) is not int or continuation_version not in (0, 1) or continuation_version and (worker_version != 1 or delivery_version != 1):
                raise ValueError('Unsupported continuation version')
            foreground_continuation = params.get('foregroundContinuationVersion',0)
            if type(foreground_continuation) is not int or foreground_continuation not in (0,1) or foreground_continuation and (foreground_version != 1 or continuation_version != 1):
                raise ValueError('Unsupported foreground continuation version')
            resumption=params.get('taskResumptionVersion',0)
            if type(resumption) is not int or resumption not in (0,1) or resumption and foreground_continuation != 1:
                raise ValueError('Unsupported task resumption version')
            worker_result=params.get('workerResultVersion',0)
            if type(worker_result) is not int or worker_result not in (0,1) or worker_result and (resumption!=1 or worker_version!=1 or delivery_version!=1):
                raise ValueError('Unsupported worker result version')
            self.worker_result_version=worker_result
            self.task_resumption_version=resumption
            self.foreground_continuation_version = foreground_continuation
            visual_planning=params.get('visualPlanningVersion',0)
            if type(visual_planning) is not int or visual_planning not in (0,1) or visual_planning and (foreground_version != 1 or chart_version != 1):
                raise ValueError('Unsupported visual planning version')
            self.visual_planning_version=visual_planning
            panel_policy = params.get('panelPolicyVersion', 0)
            if type(panel_policy) is not int or panel_policy not in (0,1): raise ValueError('Unsupported panel policy version')
            self.panel_policy_version = panel_policy
            panel_operation = params.get('panelOperationVersion', 0)
            if type(panel_operation) is not int or panel_operation not in (0, 1) or panel_operation and panel_policy != 1:
                raise ValueError('Unsupported panel operation version')
            self.panel_operation_version = panel_operation
            public_web=params.get('publicWebSourceVersion',0)
            if type(public_web) is not int or public_web not in (0,1) or public_web and (workflow_version!=1 or foreground_version!=1):
                raise ValueError('Unsupported public web source version')
            self.public_web_source_version=public_web
            self.presentation_version = version
            self.result_delivery_version = delivery_version
            self.workflow_version = workflow_version
            self.input_scope_version = input_scope_version
            self.foreground_result_version = foreground_version
            self.worker_evidence_version = worker_version
            self.continuation_version = continuation_version
            self.tool_definitions = tools
            routing = params.get('inputRouting', False)
            if not isinstance(routing, bool): raise ValueError('inputRouting must be a boolean')
            self.routing_enabled = routing
            conversation = params.get('conversationID')
            if conversation is not None and (not isinstance(conversation, str) or not conversation or len(conversation) > 128):
                raise ValueError('Invalid conversation ID')
            if foreground_version and not conversation: raise ValueError('Foreground delivery requires a conversation ID')
            self.conversation_id = conversation
            initial_owner = params.get('initialAutonomyOwner')
            if initial_owner is None and self.collaboration and any(
                    item.get('kind') == 'codex_delegation' for item in self.collaboration.pending_inputs()):
                initial_owner = CONTROL_OWNER
            if initial_owner is not None: self.control.pause(initial_owner)
            return {'schemaVersion': 1, 'sessionID': self.session_id, 'pid': os.getpid(),
                    'processGroupID': os.getpgrp(), 'product': 'Maltose', 'presentationVersion': self.presentation_version,
                    'resultDeliveryVersion': self.result_delivery_version, 'resultChartVersion': self.result_chart_version, 'workflowVersion': self.workflow_version, 'taskProgressVersion': self.task_progress_version, 'workerEvidenceVersion': self.worker_evidence_version, 'continuationVersion': self.continuation_version,
                    'inputScopeVersion': self.input_scope_version, 'foregroundResultVersion': self.foreground_result_version, 'foregroundContinuationVersion': self.foreground_continuation_version, 'taskResumptionVersion': self.task_resumption_version, 'visualPlanningVersion': self.visual_planning_version, 'panelPolicyVersion': self.panel_policy_version, 'panelOperationVersion': self.panel_operation_version, 'publicWebSourceVersion': self.public_web_source_version, 'workerResultVersion':self.worker_result_version}
        if not self._initialized.is_set():
            raise RuntimeError('Native connection is not initialized')
        if method == 'snapshot':
            return {'ready': self._ready, 'state': self.agent.state.value if self.agent else 'initializing',
                    'audioInputActive': bool(getattr(self.agent, 'audio_input_active', False)),
                    'autonomy': self.control.snapshot(),
                    'development': self.collaboration.info() if self.collaboration else None,
                    'sequence': self._sequence}
        if method == 'pause_autonomy':
            return self.control.pause(params.get('ownerID'))
        if method == 'resume_autonomy':
            if self.agent is None or not self._ready: raise RuntimeError('Agent is not ready to resume')
            if self._async_requests: raise RuntimeError('Controller operations are still draining')
            if self.collaboration and any(item.get('kind') == 'codex_delegation' for item in self.collaboration.pending_inputs()):
                raise RuntimeError('Development handoff has not been durably acknowledged by the controller')
            held = {}
            def hold_old_work():
                manager = getattr(self.brain, 'task_manager', None)
                if manager is not None: held.update(manager.store.hold_deferred_work())
            result = self.control.resume(params.get('ownerID'), params.get('leaseID'),
                intent_confirmed=params.get('intentConfirmed', False), before_resume=hold_old_work)
            return {**result, 'heldWork': held}
        if method == 'pending_inputs':
            return {'inputs': self.collaboration.pending_inputs() if self.collaboration else []}
        if method == 'acknowledge_input':
            if self.collaboration: self.collaboration.acknowledge(params.get('messageID'))
            return {'accepted': True}
        if method in {'workspace_prepare', 'workspace_inspect', 'workspace_changes'}:
            self._require_controller(params)
            return self.collaboration.workspace(method.removeprefix('workspace_'), params.get('taskID'))
        if method == 'assess_panel_intent':
            if self.panel_policy_version != 1 or params.get('runtimeSessionID') != self.session_id:
                raise PermissionError('Panel intent assessment source is unavailable')
            from maltose.ui.panel_policy import assess_panel_intent
            if params.get('executor') == 'codex':
                def checkpoint(): self._require_controller(params)
                checkpoint()
                return assess_panel_intent(self.brain.model, params.get('context'), checkpoint)
            if params.get('executor') != 'maltose': raise PermissionError('Unknown panel intent executor')
            with self.control.activity('panel_intent'):
                return assess_panel_intent(self.brain.model, params.get('context'), self.control.checkpoint)
        if method == 'execute_codex_panel':
            self._require_controller(params)
            # Validate the persisted workspace mapping before touching shared UI.
            self.collaboration.workspace('inspect', params.get('taskID'))
            from maltose.ui.native_tools import NativePanelToolAdapter
            owner = params.get('ownerSpeakerID')
            def verified_owner():
                with self._voice_lock:
                    # This controller-only UI consent does not modify brain identity,
                    # Memory access or filesystem policy. The paused lease scopes it.
                    return params.get('uiContextConsent') is True or bool(
                        owner and owner != 'unknown' and self._voice_scope == (owner, 'identified'))
            tools = NativePanelToolAdapter(self, identity_check=verified_owner, source=params.get('panelSource')).tools()
            tool = next((item for item in tools if item.name == params.get('tool')), None)
            if tool is None: raise ValueError('Unknown shared panel tool')
            result = tool.handler(params.get('arguments'))
            if result.get('error', {}).get('code') == 'identity_required':
                result['error']['message'] = 'Codex 匯出面板至本地檔案仍需授權；一般面板讀取與操作不需另行授權。'
            return result
        if method == 'select_development_repository':
            self._require_controller(params)
            return self.collaboration.select_repository(params.get('path'))
        if method == 'assess_codex':
            self._require_controller(params)
            self.collaboration.workspace('inspect', params.get('taskID'))
            context, content = params.get('context'), params.get('content')
            identity = params.get('assessmentID')
            if not isinstance(context, dict) or not isinstance(content, str) or not content.strip() or len(content.encode()) > 256 * 1024:
                raise ValueError('Invalid Codex assessment source')
            if not isinstance(identity, str) or not 1 <= len(identity) <= 128 or len(json.dumps(context).encode()) > 256 * 1024:
                raise ValueError('Invalid Codex assessment identity or context')
            reviewer = getattr(self.brain, 'assess_collaboration_result', None)
            def validate_controller():
                self._require_controller(params)
                if self._closing.is_set() or self._shutdown_requested.is_set(): raise RuntimeError('Runtime is stopping')
            def generate_assessment():
                validate_controller()
                from maltose.workflow_verification import partial
                assessment = reviewer(context, content, validate_controller) if callable(reviewer) else partial('主 Agent 核對模型尚未啟用，不能將 Codex 自述視為已驗證完成。')
                return {'mode': 'model' if callable(reviewer) else 'template', 'content': assessment['summary'], 'assessment': assessment}
            saved = self.collaboration.review({'taskID': params['taskID'], 'context': context, 'content': content},
                {'messageID': identity, 'content': '核對 Codex 本次成果；不執行工具或恢復自主工作。'}, generate_assessment, namespace='product-assessments')
            validate_controller()
            return {'assessment': saved['assessment']}
        if method == 'observe_codex':
            self._require_controller(params)
            record = params.get('record')
            if isinstance(record, dict): record = {key: value for key, value in record.items() if key != 'mainReview'}
            question = params.get('question')
            review = params.get('review', False)
            if not isinstance(review, bool): raise ValueError('Review must be a boolean')
            if question is not None:
                if not isinstance(question, dict) or not all(isinstance(question.get(key), str) and question[key] for key in ('messageID', 'content')):
                    raise ValueError('Invalid handoff question')
                if len(question['messageID']) > 128 or len(question['content'].encode()) > 64 * 1024:
                    raise ValueError('Handoff question exceeds size limit')
            observed = self.collaboration.observe(record)
            if self.brain is not None: self.brain.collaboration_context = observed
            if question is not None:
                reviewer = getattr(self.brain, 'review_collaboration', None)
                def generate():
                    self._require_controller(params)
                    if self._closing.is_set() or self._shutdown_requested.is_set(): raise RuntimeError('Runtime is stopping; review was not started')
                    if self.collaboration.last_observation != observed: raise RuntimeError('Collaboration changed before review')
                    if review:
                        outcome = record.get('outcome', {})
                        if record.get('status') != 'awaitingReview' or not record.get('lastFinishedTurnID') or outcome.get('kind') != 'completed' or outcome.get('remaining') != []:
                            raise ValueError('Main Agent review requires a completed Codex turn and its outcome')
                    if review and callable(reviewer):
                        self.hub.publish('model_started', {'source': 'maltose-coordination', 'operation': 'collaboration_review'})
                        try:
                            result = reviewer(record)
                        except Exception:
                            self.hub.publish('model_failed', {'source': 'maltose-coordination', 'operation': 'collaboration_review'})
                            raise
                        else:
                            self.hub.publish('model_finished', {'source': 'maltose-coordination', 'operation': 'collaboration_review'})
                            return result
                    return {'mode': 'template', 'content': question['content']}
                result = self.collaboration.review(record, {**question, 'reviewRequested': review}, generate)
                self._require_controller(params)
                enriched = self.collaboration.attach_review(observed, question, result)
                if self.brain is not None: self.brain.collaboration_context = enriched
                if params.get('presentationRequested') is True and self.result_delivery_version == 1:
                    from maltose.presentation import AnswerResult
                    output = AnswerResult(result['content'], result.get('spoken_summary', ''), title='麥芽糖 · Codex 任務回顧',
                        kind='needs_input', visual=result.get('visual', 'auto'), result_id=question['messageID'], chat_message_id=question['messageID'])
                    return {'accepted': True, 'reviewMode': result['mode'], 'reviewPresentation': dict(publicationID=output.result_id,
                        conversationID=record['conversationID'], messageID=output.chat_message_id, title=output.title,
                        markdown=output.display_text, createDocument=output.needs_document, spokenSummary=output.spoken_summary)}
                self.hub.publish('assistant_message', {'message_id': question['messageID'], 'content': result['content'],
                    'review_mode': result['mode'], 'source': 'maltose-coordination', 'conversation_id': record['conversationID']})
                return {'accepted': True, 'reviewMode': result['mode']}
            return {'accepted': True}
        if method == 'shutdown':
            self._graceful_shutdown = True
            self._shutdown_requested.set()
            if self.agent is not None:
                self.agent.request_shutdown()
            return {'accepted': True}
        if method == 'submit_text':
            if self.agent is None or not self._ready or self._shutdown_requested.is_set():
                raise RuntimeError('Agent is not ready for input')
            text = params.get('text')
            if not self.routing_enabled and not self.control.active:
                raise RuntimeError('Autonomy is paused; retain this input until the controller routes it')
            if not isinstance(text, str) or not text.strip():
                raise ValueError('Input text cannot be empty')
            identity = params.get('messageID')
            if identity is not None:
                if not isinstance(identity, str) or not identity or len(identity) > 128: raise ValueError('Invalid input ID')
                self.agent.submit_text(text, source='native', message_id=identity)
            else: self.agent.submit_text(text, source='native')
            return {'accepted': True}
        if method == 'submit_routed_voice':
            if self.agent is None or not self._ready or self._shutdown_requested.is_set() or not self.control.active:
                raise RuntimeError('Agent is not ready for routed voice input')
            if params.get('runtimeSessionID') != self.session_id: raise PermissionError('Voice verification belongs to another runtime')
            identity = params.get('messageID')
            if not isinstance(identity, str): raise ValueError('Invalid routed voice input ID')
            with self._voice_lock:
                proof = self._voice_proofs.get(identity)
                if proof is None or proof[0] != params.get('text') or proof[4] == 'codex':
                    raise PermissionError('Routed voice input has no matching runtime verification')
                def context_provider():
                    with self._voice_lock:
                        if self._voice_generation != proof[5] or time.monotonic() - proof[3] > 120: return None
                        manager = getattr(self.agent, '_speaker_identity_manager', None)
                        if manager is not None:
                            current = manager.snapshot()
                            if (current.user_id, current.status) != proof[2]: return None
                        return proof[1]
                if context_provider() is None: raise PermissionError('Voice verification is no longer current')
                self.agent.submit_routed_voice(proof[0], message_id=identity, context_provider=context_provider)
                self._voice_proofs.pop(identity)
            return {'accepted': True}
        if method == 'ui_action':
            action = params.get('actionID')
            allowed = {f'{domain}.{decision}' for domain in ('filesystem', 'execution', 'knowledge')
                       for decision in ('approve', 'reject')}
            if not isinstance(action, str) or action not in allowed or not isinstance(params.get('value'), dict):
                raise ValueError('Unknown native UI approval action')
            if self.action_handler is None:
                raise RuntimeError('Native approval handler is unavailable')
            if action.endswith('.approve'):
                # Approval handlers can promote artifacts or publish curated knowledge.
                # A late human click must not start new main-Agent writes during Codex control.
                with self.control.activity('approval'):
                    self.action_handler(action, params['value'])
            else:
                self.action_handler(action, params['value'])
            return {'accepted': True}
        raise ValueError('Unknown native method')

    def _events(self) -> None:
        for event in self._subscription:
            self._initialized.wait()
            if self._closed.is_set():
                return
            with self._write_lock:
                self._sequence += 1
                sequence = self._sequence
            self._send({'sessionID': self.session_id, 'conversationID': self.conversation_id or self.session_id,
                        'sequence': sequence, 'event': event.as_dict()})
            if event.type == 'state_changed' and event.payload.get('state') == 'standby' and not self._ready:
                self._ready = True
                self._send({'sessionID': self.session_id, 'notification': 'ready', 'sequence': sequence})

    def present_result(self, result) -> dict:
        if getattr(self,'worker_results',None) and self.worker_results.managed(result):
            return self.worker_results.deliver(result)
        return self._present_result(result)

    def _present_result(self, result) -> dict:
        if self.foreground_result_version == 1 and (result.workflow_ref or {}).get('foregroundID') and not (result.workflow_ref or {}).get('continuationID'):
            return self.foreground.deliver(result.result_id)
        if self.presentation_version != 1: return {'status': 'panel_unavailable', 'error': 'unsupported_presentation_version'}
        if self.result_delivery_version == 1:
            receipt = self._deliver_result(result)
            if receipt.get('chatStored') is True and getattr(self,'worker_results',None) and self.worker_results.managed(result):
                try:self.worker_results.mark_delivered(result)
                except (ValueError,RuntimeError,ConnectionError,TimeoutError):return {**receipt,'workflowStored':False}
            if receipt.get('chatStored') is True and self.workflow_version == 1:
                reference = result.workflow_ref
                main_reference = getattr(self.brain, '_active_workflow_ref', None)
                try:
                    if reference:
                        workflow = getattr(self, 'workflow', None)
                        arguments = {key: value for key, value in reference.items() if key not in {'schemaVersion', 'executionID'}}
                        if reference.get('continuationID'):
                            arguments.update(resultID=result.result_id, answerKind=result.kind, answerSummary=result.spoken_summary or result.title,
                                observations=self.continuations.observations(reference))
                            report = self.call_workflow('continuationResult', **arguments)
                            assessment = workflow.assess_result(result, reference, report) if workflow else None
                            if assessment:
                                receipt['workflowAssessment'] = assessment
                                receipt['assessmentChatStored'] = self._present_assessment(result, reference, assessment).get('chatStored') is True
                            receipt['workflowStored'] = receipt.get('assessmentChatStored', True)
                            if not reference.get('foregroundID') and receipt['workflowStored'] and result.kind not in {'needs_input', 'failed'} and assessment and assessment.get('status') == 'partial':
                                self.continuations.enqueue(result, reference)
                            return receipt
                        if self.worker_evidence_version == 1 and reference.get('attemptID') and workflow:
                            arguments['observations'] = workflow.worker_observations(reference)
                        report = self.call_workflow('pythonResult', **arguments)
                        context = report.get('assessmentContext', {})
                        if self.worker_evidence_version == 1 and reference.get('attemptID') and reference.get('workerState') == 'succeeded' and workflow and not context.get('hasUnfinishedExecution') and not context.get('hasUndeliveredResults') and not context.get('stale'):
                            from dataclasses import replace
                            assessment = workflow.assess_result(replace(result, kind='answer'), reference, report)
                            if assessment:
                                receipt['workflowAssessment'] = assessment
                                receipt['assessmentChatStored'] = self._present_assessment(result, reference, assessment).get('chatStored') is True
                    elif main_reference and result.chat_message_id and result.delivery_origin == 'main':
                        workflow = getattr(self, 'workflow', None)
                        report = self.call_workflow('mainResult', **main_reference, resultID=result.result_id,
                            answerKind=result.kind, answerSummary=result.spoken_summary or result.title,
                            observations=workflow.observations(main_reference) if workflow else [])
                        if workflow:
                            try:
                                assessment = workflow.assess_result(result, main_reference, report)
                                if assessment:
                                    receipt['workflowAssessment'] = assessment
                                    receipt['assessmentChatStored'] = self._present_assessment(result, main_reference, assessment).get('chatStored') is True
                            except AutonomyPaused: raise
                            except (ValueError, RuntimeError, ConnectionError, TimeoutError):
                                receipt['workflowAssessment'] = {'status': 'unavailable', 'summary': '成果已保存，核對狀態尚未確認。'}
                    receipt['workflowStored'] = receipt.get('assessmentChatStored', True)
                    if reference and receipt['workflowStored'] and self.continuation_version == 1:
                        receipt['productRecapManaged'] = True
                        self.continuations.enqueue(result, reference)
                except AutonomyPaused: raise
                except (ValueError, RuntimeError, ConnectionError, TimeoutError): receipt['workflowStored'] = False
            return receipt
        if not result.needs_document: return {'status': 'chat_only'}
        try:
            response = self.call_panel({'publish_document': {'publicationID': result.result_id,
                'title': result.title, 'markdown': result.display_text}})
            if response.get('ok') is not True:
                error = response.get('error')
                return {'status': 'panel_failed', 'error': error.get('code', 'operation_failed') if isinstance(error, dict) else 'operation_failed'}
            receipt = response.get('result')
            panel_id = receipt.get('panelID') if isinstance(receipt, dict) else None
            if not isinstance(panel_id, str) or not panel_id.strip() or len(panel_id.encode('utf-8')) > 256 or any(
                    ord(character) < 32 for character in panel_id):
                raise ValueError('Missing or invalid panel receipt')
            return {'status': 'panel_applied', 'panelID': panel_id}
        except (ConnectionError, TimeoutError, ValueError) as error:
            # The complete chat answer has already been emitted. A mutation with
            # an unknown outcome is not retried, nor is the original work rerun.
            return {'status': 'panel_unknown', 'error': type(error).__name__}

    def _deliver_result(self, result) -> dict:
        if getattr(self,'worker_results',None):self.worker_results.checkpoint()
        try:
            response = self.call_panel({'deliver_result': dict(publicationID=result.result_id,
                title=result.title, markdown=result.display_text, createDocument=result.needs_document,
                conversationID=self.conversation_id or self.session_id, messageID=result.chat_message_id or result.result_id,
                **({'chart': result.chart.to_dict()} if result.chart and self.result_chart_version == 1 else {}))})
            if response.get('ok') is not True: return {'status': 'delivery_failed', 'chatStored': False}
            receipt = response.get('result')
            if not isinstance(receipt, dict) or receipt.get('chatStored') is not True or receipt.get('publicationID') != result.result_id:
                raise ValueError('Missing durable result receipt')
            status = receipt.get('panelStatus')
            if status not in {'applied', 'closed', 'none'}: raise ValueError('Invalid panel receipt')
            panel_id = receipt.get('panelID')
            if status != 'none' and (not isinstance(panel_id, str) or not panel_id.strip() or len(panel_id.encode()) > 256):
                raise ValueError('Missing panel identity')
            chart_status = receipt.get('chartStatus')
            if result.chart and self.result_chart_version == 1:
                chart_id = receipt.get('chartPanelID')
                if chart_status not in {'applied', 'closed'} or not isinstance(chart_id, str) or not chart_id.strip() or len(chart_id.encode()) > 256:
                    raise ValueError('Missing native chart receipt')
            return {'chartStatus': chart_status if result.chart and self.result_chart_version == 1 else 'unsupported' if result.chart else 'none',
                'chartPanelID': receipt.get('chartPanelID'), 'status': {'applied': 'panel_applied', 'closed': 'panel_closed', 'none': 'chat_only'}[status],
                'chatStored': True, 'panelID': panel_id, 'replayed': receipt.get('replayed') is True}
        except (ConnectionError, TimeoutError, ValueError):
            return {'status': 'delivery_unknown', 'chatStored': False}

    def _present_assessment(self, result, reference, assessment):
        from maltose.presentation import AnswerResult
        import hashlib
        fingerprint = json.dumps(assessment, sort_keys=True, ensure_ascii=False)
        identity = 'assessment:' + hashlib.sha256((reference['taskID'] + ':' + result.result_id + ':' + fingerprint).encode()).hexdigest()
        if reference.get('continuationID'): identity = reference['continuationID'] + ':assessment'
        elif getattr(self,'worker_results',None) and self.worker_results.managed(result):
            self.worker_results.prepare_assessment(result)
            identity=result.result_id+':assessment'
        body = '任務核對：' + assessment['summary']
        if assessment.get('remaining'): body += '\n\n尚待處理：\n' + '\n'.join('• ' + item for item in assessment['remaining'])
        output = AnswerResult(body, '', title='任務核對', visual='none',
            kind='answer' if assessment['status'] == 'completed' else 'needs_input' if assessment['status'] == 'needs_input' else 'partial', result_id=identity)
        return self._deliver_result(output)

    def call_workflow(self, operation, **arguments):
        if self.workflow_version != 1: raise RuntimeError('Native product workflow is unavailable')
        if operation not in {'continuationAbort', 'foregroundPrepare'}: self.control.checkpoint()
        payload = {**arguments, 'schemaVersion': 1, 'operation': operation, 'runtimeSessionID': self.session_id}
        payload.setdefault('inputID', getattr(self.brain, '_active_input_id', None))
        response = self.call_panel({'workflow': {'request': payload}})
        if response.get('ok') is not True:
            raise RuntimeError(response.get('error', {}).get('message', 'Native workflow rejected the request'))
        result = response.get('result')
        if not isinstance(result, dict) or result.get('schemaVersion') != 1: raise ValueError('Invalid native workflow response')
        return result

    def observe_workflow_input(self, text, context):
        if context.input_source != 'voice': return
        try: self.call_workflow('observeInput', inputID=context.input_id, text=text,
                               speakerID=context.user_id, speakerStatus=context.speaker_status)
        except AutonomyPaused: raise
        except (ValueError, RuntimeError, TimeoutError, ConnectionError):
            self.hub.publish('workflow_input_unconfirmed', {'messageID': context.input_id})

    def panel_source(self):
        from maltose.ui.panel_policy import current_invocation, invocation_epoch
        scope = current_invocation()
        brain = self.brain
        if not scope or getattr(brain, '_workflow_thread', None) != threading.get_ident():
            raise PermissionError('Panel tool has no active Main invocation')
        identity = getattr(brain, '_active_input_id', None)
        if not isinstance(identity, str) or not identity: raise PermissionError('Panel tool has no human input source')
        epoch = invocation_epoch()
        if epoch is None or epoch != self.control.epoch: raise PermissionError('Panel invocation control epoch has expired')
        source = dict(runtimeSessionID=self.session_id, executor='maltose', inputID=identity, scopeID=scope,
                      controlEpoch=epoch)
        reference = getattr(brain, '_active_workflow_ref', None)
        if reference:
            if reference.get('inputID') != identity or any(key not in reference for key in ('taskID','requirementsRevision','planVersion')):
                raise PermissionError('Panel task reference does not match the active input')
            source['product'] = {key: reference[key] for key in ('taskID','requirementsRevision','planVersion')}
        if reference and reference.get('continuationID'):
            source['continuation'] = {key: reference[key] for key in ('taskID','inputID','requirementsRevision','planVersion','continuationID','foregroundID','resumeAfterID') if key in reference}
        return source

    def call_panel(self, command: dict, timeout: float = 30, *, file_transfer: dict | None = None, agent_source: dict | None = None) -> dict:
        if self._closed.is_set() or self._closing.is_set():
            raise ConnectionError('Native UI is disconnected')
        if 'acknowledge_panel_operations' not in command:
            self._acknowledge_panel_operations()
        request_id = uuid.uuid4().hex
        responses = queue.Queue(maxsize=1)
        with self._panel_lock:
            self._panel_requests[request_id] = responses
        try:
            self._send({'sessionID': self.session_id, 'serverRequestID': request_id, 'method': 'panel.call',
                        'params': {'request': {'schemaVersion': 1, 'requestID': request_id, 'command': command,
                                              **({'source': agent_source} if agent_source is not None else {})}, 'fileTransfer': file_transfer}})
            response = responses.get(timeout=max(timeout, 90) if agent_source is not None else timeout)
            if not response.get('ok'):
                raise ConnectionError(response.get('error', {}).get('message', 'Native UI rejected panel request'))
            result = response.get('result')
            if not isinstance(result, dict):
                raise ValueError('Invalid native panel result')
            receipts = result.pop('operationReceipts', None)
            if receipts and self.panel_operation_version == 1:
                if not isinstance(receipts,list) or len(receipts)>32 or any(not isinstance(r,dict) or set(r)!={'id','token'} or not all(isinstance(r[k],str) and 0<len(r[k])<=128 for k in ('id','token')) for r in receipts):
                    raise ValueError('Invalid native operation acknowledgement')
                with self._panel_lock:
                    self._pending_panel_acknowledgements.update({r['id']:r['token'] for r in receipts})
            if 'acknowledge_panel_operations' not in command:
                self._acknowledge_panel_operations()
            return result
        except queue.Empty as error:
            raise TimeoutError('Native panel request timed out; inspect current state before retrying a mutation') from error
        finally:
            with self._panel_lock:
                self._panel_requests.pop(request_id, None)

    def _acknowledge_panel_operations(self):
        if self.panel_operation_version != 1: return
        with self._panel_lock:
            pending=list(self._pending_panel_acknowledgements.items())[:32]
        if not pending:return
        try:
            response=self.call_panel({'acknowledge_panel_operations':{'receipts':[dict(id=identity,token=token) for identity,token in pending]}},timeout=5)
            if response.get('ok') is True:
                with self._panel_lock:
                    for identity,token in pending:
                        if self._pending_panel_acknowledgements.get(identity)==token:self._pending_panel_acknowledgements.pop(identity,None)
        except (ConnectionError,TimeoutError,ValueError):
            # The UI outcome remains known even when its delivery ACK fails.
            # A later read/operation retries only this ACK, never the mutation.
            pass

    def context(self) -> dict:
        arguments = {'agent_source': self.panel_source()} if self.panel_policy_version == 1 else {}
        return self.call_panel({'get_user_view': {}}, **arguments).get('view', {})

    def close(self) -> None:
        with self._close_lock:
            if self._closing.is_set(): return
            self._closing.set()
        self.control.close()
        with self._voice_lock:
            self._voice_proofs.clear(); self._voice_scope = None; self._voice_generation += 1
        # Finish queued final assistant/audio/shutdown events while the owning
        # app still reads stdout. EOF without a shutdown request remains abrupt.
        self._subscription.close()
        for thread in self._threads:
            if thread.name == 'maltose-native-events' and thread is not threading.current_thread():
                thread.join(timeout=1)
        self._closed.set()
        with self._panel_lock:
            for response_queue in self._panel_requests.values():
                try: response_queue.put_nowait({'ok': False, 'error': {'message': 'Native UI disconnected'}})
                except queue.Full: pass
        # Wake a thread awaiting handshake when the owner closes its pipe early.
        self._initialized.set()
