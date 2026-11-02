import io
from types import SimpleNamespace
import unittest
from maltose.runtime import EventHub
from maltose.ui.native import NativeRuntimeBridge
from maltose.ui.workflow import NativeWorkflowToolAdapter


class TaskProgressToolTests(unittest.TestCase):
    def test_progress_is_negotiated_separately_and_requires_workflow(self):
        for value in (True, -1, 2, '1'):
            bridge = NativeRuntimeBridge(EventHub(), output_stream=io.StringIO()); self.addCleanup(bridge.close)
            with self.assertRaises(ValueError): bridge._dispatch('initialize', dict(workflowVersion=1, taskProgressVersion=value))
        bridge = NativeRuntimeBridge(EventHub(), output_stream=io.StringIO()); self.addCleanup(bridge.close)
        with self.assertRaises(ValueError): bridge._dispatch('initialize', dict(taskProgressVersion=1))
        bridge = NativeRuntimeBridge(EventHub(), output_stream=io.StringIO()); self.addCleanup(bridge.close)
        self.assertEqual(bridge._dispatch('initialize', dict(workflowVersion=1))['taskProgressVersion'], 0)
        self.assertNotIn('update_task_progress', [tool.name for tool in NativeWorkflowToolAdapter(bridge).tools()])
        bridge = NativeRuntimeBridge(EventHub(), output_stream=io.StringIO()); self.addCleanup(bridge.close)
        self.assertEqual(bridge._dispatch('initialize', dict(workflowVersion=1, taskProgressVersion=1))['taskProgressVersion'], 1)
        self.assertIn('update_task_progress', [tool.name for tool in NativeWorkflowToolAdapter(bridge).tools()])

    def test_progress_uses_actual_input_and_host_versions_and_rejects_forged_metadata(self):
        calls=[]; task=dict(id='task', requirementsRevision=3, planVersion=2)
        def call(operation, **arguments):
            calls.append((operation, arguments)); return dict(task=task, inputBound=True)
        bridge=SimpleNamespace(brain=SimpleNamespace(_active_input_id='human', _active_workflow_ref=None), task_progress_version=1, call_workflow=call)
        tool=next(tool for tool in NativeWorkflowToolAdapter(bridge).tools() if tool.name=='update_task_progress')
        args=dict(stepID='research',state='running',detail='正在比較資料')
        self.assertEqual(tool.handler(args)['task'], task)
        self.assertEqual(calls[-1], ('stepProgress', dict(taskID='task', requirementsRevision=3, planVersion=2, stepID='research',stepState='running',stepDetail='正在比較資料')))
        for invalid in ({**args,'taskID':'forged'}, {**args,'state':'anything'}, {**args,'detail':'x'*1001}, {**args,'percent':99}):
            calls.clear(); self.assertEqual(tool.handler(invalid)['error'],'workflow_rejected');self.assertEqual(calls,[])
        bridge.call_workflow=lambda *a,**kw:dict(task=task,inputBound=False)
        self.assertEqual(tool.handler(args)['error'],'workflow_rejected')

    def test_nested_plan_keeps_parent_and_dependencies_separate(self):
        calls=[]
        def call(operation, **arguments):
            calls.append((operation,arguments));return dict(task=None)
        adapter=NativeWorkflowToolAdapter(SimpleNamespace(brain=SimpleNamespace(_active_input_id='human'),call_workflow=call))
        tool=next(tool for tool in adapter.tools() if tool.name=='set_task_plan')
        args=dict(criteria=['可核對的報告'],steps=[dict(id='report',title='製作報告',dependencies=[]),dict(id='chart',title='建立圖表',parentID='report',dependencies=[])])
        tool.handler(args)
        self.assertEqual(calls[-1][1]['plan']['steps'][1]['parentID'],'report')
        self.assertEqual(calls[-1][1]['plan']['steps'][1]['dependencies'],[])
