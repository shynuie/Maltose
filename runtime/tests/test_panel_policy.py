import json
import threading
import unittest
from types import SimpleNamespace

from maltose.ui.panel_policy import panel_invocation, current_invocation, assess_panel_intent
from maltose.ui.native import NativeRuntimeBridge
from maltose.ui.native_tools import NativePanelToolAdapter
from maltose.runtime import EventHub


class PanelPolicyTests(unittest.TestCase):
    def test_operation_protocol_is_opt_in_and_requires_panel_policy(self):
        for params, expected in (({}, 0), ({'panelPolicyVersion': 1}, 0),
                                 ({'panelPolicyVersion': 1, 'panelOperationVersion': 1}, 1)):
            bridge = NativeRuntimeBridge(EventHub())
            try:
                response = bridge._dispatch('initialize', params)
                self.assertEqual(response['panelOperationVersion'], expected)
                self.assertEqual(bridge.panel_operation_version, expected)
            finally: bridge.close()
        for params in ({'panelOperationVersion': 1}, {'panelPolicyVersion': 1, 'panelOperationVersion': True},
                       {'panelPolicyVersion': 1, 'panelOperationVersion': 2}):
            bridge = NativeRuntimeBridge(EventHub())
            try:
                with self.assertRaises(ValueError): bridge._dispatch('initialize', params)
            finally: bridge.close()

    def test_invocation_is_fresh_nested_thread_local_and_cleared_after_failure(self):
        self.assertIsNone(current_invocation())
        with panel_invocation():
            first = current_invocation(); other = []
            thread = threading.Thread(target=lambda: other.append(current_invocation())); thread.start(); thread.join()
            self.assertEqual(other, [None])
            with self.assertRaises(ValueError):
                with panel_invocation():
                    self.assertNotEqual(current_invocation(), first)
                    raise ValueError('interrupted turn')
            self.assertEqual(current_invocation(), first)
        self.assertIsNone(current_invocation())

    def test_bridge_source_is_from_active_invocation_and_real_brain_reference_not_tool_arguments(self):
        bridge = NativeRuntimeBridge(EventHub())
        bridge.brain = SimpleNamespace(_workflow_thread=threading.get_ident(), _active_input_id='human',
            _active_workflow_ref=dict(taskID='task',inputID='human',requirementsRevision=2,planVersion=3,continuationID='continuation',resumeAfterID='answer'))
        with self.assertRaises(PermissionError): bridge.panel_source()
        with panel_invocation(bridge.control):
            source = bridge.panel_source()
            self.assertEqual(source['inputID'], 'human')
            self.assertEqual(source['runtimeSessionID'], bridge.session_id)
            self.assertEqual(source['continuation']['resumeAfterID'], 'answer')
            self.assertEqual(source['product'], dict(taskID='task', requirementsRevision=2, planVersion=3))
            source['product']['planVersion'] = 99
            source['continuation']['planVersion'] = 99
            self.assertEqual(bridge.brain._active_workflow_ref['planVersion'], 3)
            bridge.brain._workflow_thread = -1
            with self.assertRaises(PermissionError): bridge.panel_source()
        bridge.close()

    def test_product_source_cannot_be_rebound_to_another_input_or_incomplete_version(self):
        bridge = NativeRuntimeBridge(EventHub())
        self.addCleanup(bridge.close)
        bridge.brain = SimpleNamespace(_workflow_thread=threading.get_ident(), _active_input_id='human')
        for reference in (dict(taskID='task', inputID='other', requirementsRevision=1, planVersion=1),
                          dict(taskID='task', inputID='human', requirementsRevision=1)):
            bridge.brain._active_workflow_ref = reference
            with self.subTest(reference=reference), panel_invocation(bridge.control), self.assertRaises(PermissionError):
                bridge.panel_source()

    def test_model_tool_cannot_supply_its_own_source_or_update_flag(self):
        calls = []
        source = dict(runtimeSessionID='runtime',executor='maltose',inputID='human',scopeID='scope')
        schema = dict(type='object',additionalProperties=False,properties=dict(panelID=dict(type='string'),text=dict(type='string')),required=['panelID','text'])
        bridge = SimpleNamespace(panel_policy_version=1,brain=SimpleNamespace(),panel_source=lambda: source,
            tool_definitions=[dict(name='maltose_notes_set_text',command='notes_set_text',inputSchema=schema)],
            call_panel=lambda command,**kwargs: calls.append((command,kwargs)) or dict(ok=True))
        tool = NativePanelToolAdapter(bridge).tools()[0]
        for extra in (dict(source=source),dict(update=True),dict(semanticActionVerified=True)):
            self.assertEqual(tool.handler(dict(panelID='old',text='x',**extra))['error']['code'],'invalid_argument')
        self.assertEqual(calls,[])
        self.assertTrue(tool.handler(dict(panelID='old',text='x'))['ok'])
        self.assertEqual(calls[0][1],dict(agent_source=source))

    def test_control_handoff_expires_the_original_invocation_even_if_brain_fields_remain(self):
        bridge=NativeRuntimeBridge(EventHub())
        bridge.brain=SimpleNamespace(_workflow_thread=threading.get_ident(),_active_input_id='human',_active_workflow_ref=None)
        with panel_invocation(bridge.control):
            old=bridge.panel_source()
            bridge.control.pause('other-owner')
            with self.assertRaises(PermissionError):bridge.panel_source()
            self.assertNotEqual(old['controlEpoch'],bridge.control.epoch)
        bridge.close()

    def test_intent_contract_requires_exact_human_evidence_unique_target_and_no_tools(self):
        context=dict(humanText='更新指定的筆記',command='notes_set_text',targetIDs=['notes'],allowedActionEvidence=['更新'])
        allowed=dict(decision='allow',command='notes_set_text',targetIDs=['notes'],evidence=context['humanText'],reason='人員明確指定',actionEvidence='更新',targetEvidence='筆記',discardEvidence='')
        def assess(value, *, tools=False):
            seen=[]
            def complete(messages, schemas):
                self.assertEqual(schemas,[]);self.assertIn('panel_mutation_intent',messages[0]['content']);seen.append(messages)
                return dict(choices=[dict(message=dict(content=json.dumps(value),**({'tool_calls':[{}]} if tools else {})))])
            return assess_panel_intent(SimpleNamespace(complete=complete), context, lambda: None)
        self.assertEqual(assess(allowed),allowed)
        for edit in (dict(evidence='模型建議更新'),dict(targetIDs=['other']),dict(targetIDs=['notes','notes']),dict(command='close_panel'),dict(update=True),dict(semanticActionVerified=True)):
            with self.subTest(edit=edit),self.assertRaises(ValueError): assess({**allowed,**edit})
        with self.assertRaises(ValueError):assess(allowed,tools=True)
        denied=dict(decision='deny',command='notes_set_text',targetIDs=[],evidence='',reason='人員要求新增成果',actionEvidence='',targetEvidence='',discardEvidence='')
        self.assertEqual(assess(denied)['decision'],'deny')
        with self.assertRaises(ValueError): assess({**denied,'evidence':context['humanText']})

    def test_pause_during_intent_assessment_does_not_return_an_authorization(self):
        from maltose.runtime.control import AutonomyPaused
        count=[]
        def checkpoint():
            count.append(1)
            if len(count)==2:raise AutonomyPaused('new control owner')
        model=SimpleNamespace(complete=lambda *_:dict(choices=[dict(message=dict(content='{}'))]))
        with self.assertRaises(AutonomyPaused):assess_panel_intent(model,dict(humanText='更新',command='x',targetIDs=['notes']),checkpoint)

    def test_unfamiliar_human_edit_phrase_is_grounded_semantically_without_a_closed_verb_list(self):
        context=dict(humanText='替指定的筆記潤飾內容',command='notes_set_text',targetIDs=['notes'],allowedActionEvidence=['更新'],effectCategory='content')
        proposal=dict(decision='allow',command='notes_set_text',targetIDs=['notes'],evidence=context['humanText'],actionEvidence='潤飾',targetEvidence='指定的筆記',discardEvidence='',reason='明確修改既有內容')
        grounding=dict(category='content',targetIDs=['notes'],actionEvidence='潤飾',targetEvidence='指定的筆記',reason='潤飾是修改指定內容')
        calls=[]
        def complete(messages,tools):
            self.assertEqual(tools,[]);calls.append(messages[0]['content'])
            return dict(choices=[dict(message=dict(content=json.dumps(proposal if len(calls)==1 else grounding)))])
        result=assess_panel_intent(SimpleNamespace(complete=complete),context,lambda:None)
        self.assertTrue(result['semanticActionVerified']);self.assertEqual(len(calls),2)
        self.assertIn('panel_mutation_grounding',calls[-1])

    def test_read_only_phrase_cannot_gain_write_permission_from_a_mistaken_initial_verdict(self):
        context=dict(humanText='閱讀指定的筆記，告訴我重點',command='notes_set_text',targetIDs=['notes'],allowedActionEvidence=['更新'],effectCategory='content')
        proposal=dict(decision='allow',command='notes_set_text',targetIDs=['notes'],evidence=context['humanText'],actionEvidence='閱讀',targetEvidence='指定的筆記',discardEvidence='',reason='錯誤的初步判斷')
        grounding=dict(category='none',targetIDs=['notes'],actionEvidence='閱讀',targetEvidence='指定的筆記',reason='閱讀與說明沒有授權改寫筆記')
        answers=iter([proposal,grounding])
        model=SimpleNamespace(complete=lambda *_:{'choices':[{'message':{'content':json.dumps(next(answers))}}]})
        result=assess_panel_intent(model,context,lambda:None)
        self.assertEqual(result['decision'],'deny');self.assertNotIn('semanticActionVerified',result)

    def test_discarding_unsaved_work_requires_an_additional_exact_human_consent_span(self):
        text='捨棄未儲存修改，重設流程圖'
        context=dict(humanText=text,command='flowchart_new',targetIDs=['canvas'],allowedActionEvidence=['重設'],effectCategory='content',requiresDiscardConsent=True)
        proposal=dict(decision='allow',command='flowchart_new',targetIDs=['canvas'],evidence=text,actionEvidence='重設',targetEvidence='流程圖',discardEvidence='',reason='明確要求重設')
        def model(value):return SimpleNamespace(complete=lambda *_:{'choices':[{'message':{'content':json.dumps(value)}}]})
        with self.assertRaises(ValueError):assess_panel_intent(model(proposal),context,lambda:None)
        with self.assertRaises(ValueError):assess_panel_intent(model({**proposal,'discardEvidence':'模型宣稱可捨棄'}),context,lambda:None)
        accepted=assess_panel_intent(model({**proposal,'discardEvidence':'捨棄未儲存修改'}),context,lambda:None)
        self.assertEqual(accepted['decision'],'allow')
