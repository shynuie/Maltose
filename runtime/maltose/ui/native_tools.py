"""Typed panel capabilities supplied by the owning native app.

Filesystem operations use FileService and transfer validated content; an App
filesystem reader never becomes an escape from the Agent's configured roots.
"""
from __future__ import annotations
import math
import re
from typing import Any
from maltose.agent.capabilities import CapabilityTool
from maltose.ui.native_files import NativePanelFileAdapter


def validate_arguments(schema: dict, value: Any) -> None:
    kind = schema.get('type')
    expected = {'object': dict, 'array': list, 'string': str, 'boolean': bool,
                'integer': int, 'number': (int, float)}.get(kind)
    if expected is None or not isinstance(value, expected):
        raise ValueError('Panel arguments do not match the declared schema')
    if kind in ('integer', 'number') and (isinstance(value, bool) or not math.isfinite(value)):
        raise ValueError('Panel numeric arguments must be finite numbers')
    if 'enum' in schema and value not in schema['enum']:
        raise ValueError('Panel argument is not one of the allowed values')
    if kind == 'object':
        properties = schema.get('properties', {})
        if any(name not in value for name in schema.get('required', [])):
            raise ValueError('Required panel argument is missing')
        if schema.get('additionalProperties') is False and set(value) - set(properties):
            raise ValueError('Unknown panel arguments are not accepted')
        for key, child in value.items():
            if key in properties: validate_arguments(properties[key], child)
    if kind == 'array':
        for item in value: validate_arguments(schema['items'], item)


class NativePanelToolAdapter:
    private_reads = {'flowchart_save'}  # Local-file export retains identity/consent checks.
    file_operations = {'chart_open_csv', 'image_add_file', 'flowchart_open', 'flowchart_save'}

    def __init__(self, bridge, *, identity_check=None, source=None):
        self.bridge = bridge
        self.identity_check = identity_check
        self.source = source

    def tools(self) -> list[CapabilityTool]:
        tools = []
        for definition in self.bridge.tool_definitions:
            name, command = definition.get('name'), definition.get('command')
            schema = definition.get('inputSchema')
            if not isinstance(command, str) or not re.fullmatch('[a-z][a-z0-9_]*', command) or name != 'maltose_' + command or len(name) > 64:
                raise ValueError('Invalid native panel tool name')
            if not isinstance(schema, dict) or schema.get('type') != 'object':
                raise ValueError('Native panel tool schema must be an object')
            def dispatch(arguments, command=command, schema=schema):
                validate_arguments(schema, arguments)
                brain = self.bridge.brain
                source = self.source
                if getattr(self.bridge, 'panel_policy_version', 0) == 1 and source is None:
                    source = self.bridge.panel_source()
                verified = self.identity_check if self.identity_check is not None else getattr(brain, '_identity_is_known', None)
                local_native = source is not None and source.get('executor') == 'maltose' and getattr(brain, '_active_input_source', None) == 'native'
                if command in self.private_reads and not (local_native or (callable(verified) and verified())):
                    return {'ok': False, 'error': {'code': 'identity_required', 'message': 'Local-file export requires verified identity or the existing native export authorization.'}}
                if command in self.file_operations:
                    result = NativePanelFileAdapter(self.bridge, source=source).call(command, arguments)
                    if result.get("error", {}).get("code") == "outcome_unknown":
                        result["retryable"] = False
                    return result
                result = self.bridge.call_panel({command: arguments}, **({'agent_source': source} if source is not None else {}))
                if result.get('error',{}).get('code') == 'outcome_unknown': result['retryable'] = False
                return result
            def call(arguments, operation=dispatch):
                try:
                    return operation(arguments)
                except (TimeoutError, ConnectionError) as error:
                    return {'ok': False, 'error': {'code': 'outcome_unknown', 'message': str(error) + ' Inspect the actual panel state before retrying.'}, 'retryable': False}
                except PermissionError as error:
                    return {'ok': False, 'error': {'code': 'access_denied', 'message': str(error)}}
                except (ValueError, TypeError, KeyError) as error:
                    return {'ok': False, 'error': {'code': 'invalid_argument', 'message': str(error)}}
                except OSError as error:
                    return {'ok': False, 'error': {'code': 'file_error', 'message': str(error)}}
                except RuntimeError as error:
                    return {'ok': False, 'error': {'code': 'invalid_state', 'message': str(error)}}
            tools.append(CapabilityTool(name, str(definition.get('description', command)), schema, call))
        return tools
