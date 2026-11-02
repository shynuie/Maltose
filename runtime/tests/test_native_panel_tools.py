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

    def test_unverified_panel_reads_are_allowed_but_local_export_still_requires_identity(self):
        calls=[]
        bridge = SimpleNamespace(brain=SimpleNamespace(_identity_is_known=lambda: False),
                                 file_service=None,
                                 tool_definitions=[self.definition('read_panel'), self.definition('flowchart_save')],
                                 call_panel=lambda command: calls.append(command) or {'ok': True})
        tools = NativePanelToolAdapter(bridge).tools()
        self.assertTrue(tools[0].handler({'panelID': 'notes'})['ok'])
        self.assertEqual(calls,[{'read_panel':{'panelID':'notes'}}])
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

    def test_operation_receipt_is_acknowledged_privately_without_exposing_token_to_model(self):
        class Output:
            def __init__(self): self.lines = queue.Queue()
            def write(self, line): self.lines.put(json.loads(line))
            def flush(self): pass
        output = Output()
        bridge = NativeRuntimeBridge(EventHub(), output_stream=output)
        self.addCleanup(bridge.close)
        bridge.panel_operation_version = 1
        results = []
        worker = threading.Thread(target=lambda: results.append(bridge.call_panel({'notes_set_text': {'panelID': 'notes', 'text': 'done'}}, timeout=2)))
        worker.start()
        mutation = output.lines.get(timeout=2)
        def reply(packet, result):
            bridge.receive_line(json.dumps(dict(schemaVersion=1, sessionID=bridge.session_id,
                replyTo=packet['serverRequestID'], ok=True, result=result)))
        reply(mutation, dict(ok=True, result=dict(panelID='notes'), operationReceipts=[dict(id='operation', token='private-token')]))
        acknowledgement = output.lines.get(timeout=2)
        request = acknowledgement['params']['request']
        self.assertNotIn('source', request)
        self.assertEqual(request['command'], {'acknowledge_panel_operations': {'receipts': [dict(id='operation', token='private-token')]}})
        reply(acknowledgement, dict(ok=True))
        worker.join(timeout=2)
        self.assertFalse(worker.is_alive())
        self.assertEqual(results, [dict(ok=True, result=dict(panelID='notes'))])
        self.assertEqual(bridge._pending_panel_acknowledgements, {})
        self.assertNotIn('private-token', json.dumps(results))
        self.assertTrue(output.lines.empty(), 'The mutation is sent once')

    def test_lost_receipt_ack_preserves_known_result_and_only_retries_ack_before_next_read(self):
        class Output:
            def __init__(self): self.lines = queue.Queue()
            def write(self, line): self.lines.put(json.loads(line))
            def flush(self): pass
        output = Output()
        bridge = NativeRuntimeBridge(EventHub(), output_stream=output)
        self.addCleanup(bridge.close)
        bridge.panel_operation_version = 1
        results = []
        def reply(packet, result=None, ok=True):
            bridge.receive_line(json.dumps(dict(schemaVersion=1, sessionID=bridge.session_id,
                replyTo=packet['serverRequestID'], ok=ok, result=result,
                **({} if ok else {'error': {'message': 'ACK response lost'}}))))
        worker = threading.Thread(target=lambda: results.append(bridge.call_panel({'notes_set_text': {'panelID': 'notes', 'text': 'done'}}, timeout=2)))
        worker.start()
        mutation = output.lines.get(timeout=2)
        reply(mutation, dict(ok=True, result=dict(panelID='notes'), operationReceipts=[dict(id='operation', token='private-token')]))
        failed_ack = output.lines.get(timeout=2)
        reply(failed_ack, ok=False)
        worker.join(timeout=2)
        self.assertFalse(worker.is_alive())
        self.assertTrue(results[0]['ok'], 'A known native outcome is not changed into a failed mutation by ACK loss')
        self.assertEqual(bridge._pending_panel_acknowledgements, {'operation': 'private-token'})
        reader = threading.Thread(target=lambda: results.append(bridge.call_panel({'read_panel': {'panelID': 'notes'}}, timeout=2)))
        reader.start()
        retried_ack = output.lines.get(timeout=2)
        self.assertEqual(retried_ack['params']['request']['command'], failed_ack['params']['request']['command'])
        self.assertNotEqual(retried_ack['serverRequestID'], failed_ack['serverRequestID'])
        reply(retried_ack, dict(ok=True))
        read = output.lines.get(timeout=2)
        self.assertEqual(read['params']['request']['command'], {'read_panel': {'panelID': 'notes'}})
        reply(read, dict(ok=True, result=dict(text='done', operationHistory=[dict(id='operation', phase='completed', historical=True)])))
        reader.join(timeout=2)
        self.assertFalse(reader.is_alive())
        self.assertEqual(results[1]['result']['text'], 'done')
        self.assertEqual(bridge._pending_panel_acknowledgements, {})
        self.assertTrue(output.lines.empty(), 'A failed ACK must never replay the original UI mutation')
