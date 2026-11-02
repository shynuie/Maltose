"""Main-Agent delegation through the native controller's durable input outbox."""
from __future__ import annotations

import json
import uuid

from maltose.agent.capabilities import CapabilityTool
from maltose.codex.native_service import CONTROL_OWNER
from maltose.ui.native_tools import validate_arguments


class NativeCodexToolAdapter:
    def __init__(self, bridge): self.bridge = bridge

    def tools(self):
        schema = {'type': 'object', 'additionalProperties': False, 'properties': {
            'objective': {'type': 'string'},
            'constraints': {'type': 'array', 'items': {'type': 'string'}},
            'acceptanceCriteria': {'type': 'array', 'items': {'type': 'string'}},
            'context': {'type': 'string'},
        }, 'required': ['objective', 'constraints', 'acceptanceCriteria']}

        def delegate(arguments):
            validate_arguments(schema, arguments)
            brain = self.bridge.brain
            verified = callable(getattr(brain, '_identity_is_known', None)) and brain._identity_is_known()
            native = getattr(brain, '_active_input_source', None) == 'native'
            if not verified and not native:
                return {'ok': False, 'error': {'code': 'identity_required', 'message': 'Development delegation requires a native human request or verified speaker.'}}
            if self.bridge.collaboration is None or not self.bridge.routing_enabled:
                return {'ok': False, 'error': {'code': 'unavailable', 'message': 'Native Codex collaboration is not connected.'}}
            if not self.bridge.collaboration.info()['available']:
                return {'ok': False, 'error': {'code': 'repository_required', 'message': 'Configure an authorized development repository first.'}}
            if not arguments['objective'].strip() or not arguments['acceptanceCriteria']:
                raise ValueError('Delegation needs an objective and acceptance criteria')
            if len(json.dumps(arguments).encode()) > 64 * 1024: raise ValueError('Delegation exceeds size limit')
            if not self.bridge.control.active:
                return {'ok': False, 'error': {'code': 'paused', 'message': 'Maltose does not currently own autonomous execution.'}}
            task_id, message_id = str(uuid.uuid4()), str(uuid.uuid4())
            payload = dict(kind='codex_delegation', messageID=message_id, taskID=task_id,
                conversationID=self.bridge.conversation_id, runtimeSessionID=self.bridge.session_id,
                content=json.dumps(arguments, ensure_ascii=False), delegation=arguments,
                source='delegation', author='maltose', recipient='codex',
                inputSource='native' if native else 'voice',
                speaker=dict(userID=brain._active_user_id if verified else None, status='identified' if verified else 'unknown'))
            source_input_id = getattr(brain, '_active_input_id', None)
            if source_input_id: payload['sourceInputID'] = source_input_id
            # Persist before publishing or closing admission. Do not wait for App RPCs
            # inside this tool: the current tool/conversation must be able to drain.
            self.bridge.collaboration.save_input(payload)
            self.bridge.control.pause(CONTROL_OWNER)
            self.bridge.hub.publish('input_routed', payload)
            return {'ok': True, 'accepted': True, 'taskID': task_id, 'messageID': message_id,
                    'status': 'handing_off', 'executionCompleted': False}

        return [CapabilityTool('delegate_to_codex',
            'Delegate a scoped development task to Codex in the configured repository. '
            'Provide the objective, constraints, acceptance criteria and relevant context. '
            'A native human request can delegate to the already-authorized repository without claiming a verified speaker or Memory access. '
            'Maltose pauses autonomous execution while Codex and the user work; acceptance is not completion.',
            schema, delegate)]
