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
from maltose.runtime.control import AutonomyControl
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
        self.file_service = None
        self.action_handler = None
        self._panel_lock = threading.Lock()
        self._panel_requests: dict[str, queue.Queue] = {}
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
        if brain is not None and hasattr(brain, 'tools'):
            brain.control_gate = self.control
            brain.tools.control_gate = self.control
            if self.collaboration: brain.collaboration_context = self.collaboration.last_observation
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
                if request.get('method') in {'workspace_prepare', 'workspace_inspect', 'workspace_changes', 'observe_codex', 'select_development_repository', 'execute_codex_panel'}:
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
            self.tool_definitions = tools
            routing = params.get('inputRouting', False)
            if not isinstance(routing, bool): raise ValueError('inputRouting must be a boolean')
            self.routing_enabled = routing
            conversation = params.get('conversationID')
            if conversation is not None and (not isinstance(conversation, str) or not conversation or len(conversation) > 128):
                raise ValueError('Invalid conversation ID')
            self.conversation_id = conversation
            initial_owner = params.get('initialAutonomyOwner')
            if initial_owner is None and self.collaboration and any(
                    item.get('kind') == 'codex_delegation' for item in self.collaboration.pending_inputs()):
                initial_owner = CONTROL_OWNER
            if initial_owner is not None: self.control.pause(initial_owner)
            return {'schemaVersion': 1, 'sessionID': self.session_id, 'pid': os.getpid(),
                    'processGroupID': os.getpgrp(), 'product': 'Maltose'}
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
            tools = NativePanelToolAdapter(self, identity_check=verified_owner).tools()
            tool = next((item for item in tools if item.name == params.get('tool')), None)
            if tool is None: raise ValueError('Unknown shared panel tool')
            result = tool.handler(params.get('arguments'))
            if result.get('error', {}).get('code') == 'identity_required':
                result['error']['message'] = 'Codex 尚未取得目前任務的面板讀取授權；請從 Codex 選單允許讀取面板內容。'
            return result
        if method == 'select_development_repository':
            self._require_controller(params)
            return self.collaboration.select_repository(params.get('path'))
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
            self._send({'sessionID': self.session_id, 'sequence': sequence, 'event': event.as_dict()})
            if event.type == 'state_changed' and event.payload.get('state') == 'standby' and not self._ready:
                self._ready = True
                self._send({'sessionID': self.session_id, 'notification': 'ready', 'sequence': sequence})

    def call_panel(self, command: dict, timeout: float = 30, *, file_transfer: dict | None = None) -> dict:
        if self._closed.is_set() or self._closing.is_set():
            raise ConnectionError('Native UI is disconnected')
        request_id = uuid.uuid4().hex
        responses = queue.Queue(maxsize=1)
        with self._panel_lock:
            self._panel_requests[request_id] = responses
        try:
            self._send({'sessionID': self.session_id, 'serverRequestID': request_id, 'method': 'panel.call',
                        'params': {'request': {'schemaVersion': 1, 'requestID': request_id, 'command': command}, 'fileTransfer': file_transfer}})
            response = responses.get(timeout=timeout)
            if not response.get('ok'):
                raise ConnectionError(response.get('error', {}).get('message', 'Native UI rejected panel request'))
            result = response.get('result')
            if not isinstance(result, dict):
                raise ValueError('Invalid native panel result')
            return result
        except queue.Empty as error:
            raise TimeoutError('Native panel request timed out; inspect current state before retrying a mutation') from error
        finally:
            with self._panel_lock:
                self._panel_requests.pop(request_id, None)

    def context(self) -> dict:
        return self.call_panel({'get_user_view': {}}).get('view', {})

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
