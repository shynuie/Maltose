import io
import json
import queue
import threading
import unittest
from types import SimpleNamespace
from maltose.runtime import EventHub
from maltose.ui.native import NativeRuntimeBridge
from maltose.ui.native_files import NativePanelFileAdapter
from maltose.ui.native_tools import NativePanelToolAdapter, validate_arguments


class NativePanelToolsTests(unittest.TestCase):
    def test_native_brain_does_not_advertise_unrendered_web_presentation_tools(self):
        from maltose.agent.taskbrain import TaskBrain
        brain = TaskBrain(SimpleNamespace(), ui_publisher=lambda *_: None, presentation_tools_enabled=False)
        self.assertFalse(brain.tools.has('display_ui_card'))
        self.assertFalse(brain.tools.has('request_ui_confirmation'))
        self.assertFalse(brain.tools.has('get_ui_state'))
        web_brain = TaskBrain(SimpleNamespace(), ui_publisher=lambda *_: None)
        self.assertTrue(web_brain.tools.has('display_ui_card'))

    def definition(self, command):
        return {'name': 'maltose_' + command, 'command': command, 'description': 'test', 'inputSchema': {
            'type': 'object', 'additionalProperties': False, 'properties': {'panelID': {'type': 'string'}}, 'required': ['panelID']}}

    def test_registry_dispatches_typed_commands_and_rejects_unknown_arguments(self):
        calls = []
        bridge = SimpleNamespace(brain=SimpleNamespace(_identity_is_known=lambda: True),
                                 tool_definitions=[self.definition('read_panel')], call_panel=lambda command: calls.append(command) or {'ok': True})
        tool = NativePanelToolAdapter(bridge).tools()[0]
        self.assertTrue(tool.handler({'panelID': 'notes'})['ok'])
        self.assertEqual(calls, [{'read_panel': {'panelID': 'notes'}}])
        for invalid in [{}, {'panelID': 7}, {'panelID': 'notes', 'unexpected': True}]:
            self.assertEqual(tool.handler(invalid)['error']['code'], 'invalid_argument')
        self.assertEqual(len(calls), 1)

    def test_unverified_ui_reads_and_disabled_file_io_never_reach_native_app(self):
        bridge = SimpleNamespace(brain=SimpleNamespace(_identity_is_known=lambda: False),
                                 file_service=None,
                                 tool_definitions=[self.definition('read_panel'), self.definition('flowchart_save')],
                                 call_panel=lambda _: self.fail('Unsafe native request'))
        tools = NativePanelToolAdapter(bridge).tools()
        self.assertEqual(tools[0].handler({'panelID': 'notes'})['error']['code'], 'identity_required')
        self.assertEqual(tools[1].handler({'panelID': 'canvas'})['error']['code'], 'identity_required')
        bridge.brain._identity_is_known = lambda: True
        with self.assertRaises(PermissionError):
            NativePanelFileAdapter(bridge).call('flowchart_save', {'panelID': 'canvas', 'path': '/tmp/test'})

    def test_timeout_returns_unknown_outcome_without_crashing_the_agent_or_authorizing_retry(self):
        def timeout(_): raise TimeoutError('native panel response timed out')
        bridge = SimpleNamespace(brain=SimpleNamespace(_identity_is_known=lambda: True),
            tool_definitions=[self.definition('read_panel')], call_panel=timeout)
        result = NativePanelToolAdapter(bridge).tools()[0].handler({'panelID': 'notes'})
        self.assertFalse(result['ok'])
        self.assertEqual(result['error']['code'], 'outcome_unknown')
        self.assertFalse(result['retryable'])

    def test_numeric_validation_does_not_accept_boolean_nan_or_infinity(self):
        for value in [True, float('nan'), float('inf')]:
            with self.assertRaises(ValueError): validate_arguments({'type': 'number'}, value)
        with self.assertRaises(ValueError): validate_arguments({'type': 'integer'}, 1.5)
        validate_arguments({'type': 'number'}, 1.5)

    def test_panel_call_response_roundtrip_and_disconnect_wakes_waiters(self):
        class Output:
            def __init__(self): self.lines = queue.Queue()
            def write(self, line): self.lines.put(json.loads(line))
            def flush(self): pass
        output = Output()
        bridge = NativeRuntimeBridge(EventHub(), output_stream=output)
        results = []
        def request():
            try: results.append(bridge.call_panel({'read_panel': {'panelID': 'notes'}}, timeout=2))
            except Exception as error: results.append(error)
        worker = threading.Thread(target=request); worker.start()
        command = output.lines.get(timeout=2)
        self.assertEqual(command['method'], 'panel.call')
        bridge.receive_line(json.dumps({'schemaVersion': 1, 'sessionID': bridge.session_id,
                                       'replyTo': command['serverRequestID'], 'ok': True,
                                       'result': {'ok': True, 'result': {'text': 'content'}}}))
        worker.join(timeout=2)
        self.assertEqual(results[0]['result']['text'], 'content')
        second = threading.Thread(target=request); second.start(); output.lines.get(timeout=2)
        bridge.close(); second.join(timeout=2)
        self.assertIsInstance(results[1], ConnectionError)
