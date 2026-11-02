import json
from pathlib import Path
import tempfile
import threading
from types import SimpleNamespace
import unittest

from maltose.agent import TaskBrain, MemoryStore, VoiceAgent, AgentConfig
from maltose.agent.brain import TurnContext
from maltose.presentation import AnswerResult
from maltose.runtime.control import AutonomyPaused
from maltose.ui.workflow import NativeWorkflowToolAdapter
from maltose.workflow_verification import assess_result, validate_assessment


class WorkflowVerificationTests(unittest.TestCase):
    def context(self):
        return dict(complete=True, requirementsRevision=2, planVersion=1, criteria=['讀取原文', '保留限制'],
            evidence=[dict(id='observed', source='observed', kind='sourceRead', verdict='passed',
                detail='實際原文內容；本檔案中的「ignore system」只能是資料。')])

    def review(self, context):
        return dict(status='completed', summary='原文與限制已核對。', checks=[dict(criterion=value, evidenceIDs=['observed']) for value in context['criteria']],
                    remaining=[], resolvedFailures={}, explanation='核對實際讀回資料與完整輸出。')

    def brain(self, handler):
        model = SimpleNamespace(complete=handler)
        return SimpleNamespace(model=model, _complete_model=handler)

    def test_tool_free_review_uses_complete_requirements_source_and_result_without_reexecuting_work(self):
        context = self.context(); calls = []
        def model(messages, tools):
            calls.append(messages)
            self.assertEqual(tools, [])
            value = json.loads(messages[-1]['content'])
            self.assertFalse(value['trustedAsInstruction'])
            self.assertEqual(value['context'], context)
            self.assertEqual(value['eligibleEvidenceIDs'], ['observed'])
            self.assertEqual(value['result']['full_text'], '完整原文整理')
            self.assertEqual(value['result']['limitations'], ['來源限制'])
            return {'choices': [{'message': {'content': json.dumps(self.review(context))}}]}
        result = AnswerResult('完整原文整理', '摘要', limitations=('來源限制',))
        self.assertEqual(assess_result(self.brain(model), context, result)['status'], 'completed')
        self.assertEqual(len(calls), 1)
        self.assertEqual(result.full_text, '完整原文整理')
        self.assertEqual(result.limitations, ('來源限制',))

    def test_unknown_sdk_observations_remain_chronology_but_are_explicitly_excluded_from_witnesses(self):
        context = self.context()
        context['evidence'] += [dict(id='sdk-diff', source='observed', kind='execution', verdict='unknown', detail='git diff'),
                                dict(id='self-report', source='reported', kind='report', verdict='passed', detail='tests passed')]
        def model(messages, tools):
            payload = json.loads(messages[-1]['content'])
            self.assertEqual(payload['eligibleEvidenceIDs'], ['observed'])
            self.assertEqual(len(payload['context']['evidence']), 3)
            self.assertIn('EXCLUSIVE', messages[0]['content'])
            invalid = self.review(context); invalid['checks'][0]['evidenceIDs'].append('sdk-diff')
            return {'choices': [{'message': {'content': json.dumps(invalid)}}]}
        assessed = assess_result(self.brain(model), context, AnswerResult('完整來源整理', ''))
        self.assertEqual(assessed['status'], 'partial')
        self.assertEqual(assessed['checks'], [], 'Invalid witnesses must be rejected, never silently stripped')

    def test_no_second_model_call_for_missing_or_incomplete_evidence_partial_result_or_oversized_context(self):
        def forbidden(*args): self.fail('No model call is warranted')
        brain = self.brain(forbidden); result = AnswerResult('結果', '摘要')
        self.assertEqual(assess_result(brain, {**self.context(), 'evidence': []}, result)['status'], 'partial')
        self.assertEqual(assess_result(brain, {**self.context(), 'complete': False}, result)['status'], 'partial')
        self.assertEqual(assess_result(brain, {**self.context(), 'extra': 'x' * 200000}, result)['status'], 'partial')
        self.assertIsNone(assess_result(brain, self.context(), AnswerResult('部分結果', '', kind='partial')))

    def test_long_evidence_references_round_trip_exactly_without_mutating_original_receipts(self):
        context = self.context(); identity = 'workspace:' + 'long-immutable-id-' * 12
        context['evidence'][0]['id'] = identity
        def model(messages, tools):
            payload = json.loads(messages[-1]['content']); reference = payload['eligibleEvidenceIDs'][0]
            self.assertEqual(reference, 'e1'); self.assertEqual(payload['evidenceOrder'], ['e1'])
            value = self.review(context)
            for check in value['checks']: check['evidenceIDs'] = [reference]
            return {'choices': [{'message': {'content': json.dumps(value)}}]}
        saved = assess_result(self.brain(model), context, AnswerResult('完整結果', ''))
        self.assertEqual(saved['status'], 'completed')
        self.assertEqual(saved['checks'][0]['evidenceIDs'], [identity])
        self.assertEqual(context['evidence'][0]['id'], identity)

    def test_uuid_tool_witnesses_use_collision_free_aliases_and_reject_miscopied_store_keys(self):
        context=self.context()
        identities=['tool:5b3aea8cdae24566ba0a3b668620bb0a','tool:9bbd4c3d79314966a09a3e274174abac']
        context['evidence']=[dict(context['evidence'][0],id='e2')]+[dict(context['evidence'][0],id=key) for key in identities]
        original=json.loads(json.dumps(context))
        def model(messages,tools):
            payload=json.loads(messages[-1]['content']);ids=payload['eligibleEvidenceIDs']
            self.assertEqual(len(set(ids)),3)
            self.assertEqual(ids[0],'e2')
            self.assertNotIn('e2',ids[1:])
            self.assertTrue(all(len(key)<10 for key in ids))
            value=self.review(context)
            for check in value['checks']:check['evidenceIDs']=ids[1:]
            return {'choices':[{'message':{'content':json.dumps(value)}}]}
        saved=assess_result(self.brain(model),context,AnswerResult('完整來源與限制',''))
        self.assertEqual(saved['status'],'completed')
        self.assertEqual(saved['checks'][0]['evidenceIDs'],identities)
        for wrong in ('tool:5b3aea8cdae24566a09a3e274174abac',identities[0],'e999'):
            def invalid(messages,tools):
                response=model(messages,tools);value=json.loads(response['choices'][0]['message']['content'])
                value['checks'][0]['evidenceIDs'][0]=wrong
                return {'choices':[{'message':{'content':json.dumps(value)}}]}
            self.assertEqual(assess_result(self.brain(invalid),context,AnswerResult('完整結果',''))['status'],'partial')
        self.assertEqual(context,original)

    def test_short_criterion_references_preserve_exact_human_text_and_reject_unknown_missing_or_duplicate_keys(self):
        context=self.context();context['criteria']=['完整計畫。', 'criterion-1']
        def model(messages,tools):
            payload=json.loads(messages[-1]['content']);references=payload['criterionReferences']
            self.assertEqual(payload['context']['criteria'],context['criteria'])
            self.assertNotIn('criterion-1',references)
            value=self.review(context)
            for check,key in zip(value['checks'],references):check['criterion']=key
            return {'choices':[{'message':{'content':json.dumps(value)}}]}
        saved=assess_result(self.brain(model),context,AnswerResult('完整計畫與限制。',''))
        self.assertEqual(saved['status'],'completed')
        self.assertEqual([check['criterion'] for check in saved['checks']],context['criteria'])
        for mode in ('unknown','duplicate','missing','punctuation'):
            def invalid(messages,tools):
                response=model(messages,tools);value=json.loads(response['choices'][0]['message']['content'])
                if mode=='unknown':value['checks'][0]['criterion']='criterion-forged'
                if mode=='duplicate':value['checks'][1]['criterion']=value['checks'][0]['criterion']
                if mode=='missing':value['checks'].pop()
                if mode=='punctuation':value['checks'][0]['criterion']='完整計畫'
                return {'choices':[{'message':{'content':json.dumps(value)}}]}
            self.assertEqual(assess_result(self.brain(invalid),context,AnswerResult('完整計畫與限制。',''))['status'],'partial',mode)
        self.assertEqual(context['criteria'],['完整計畫。','criterion-1'])

    def test_invalid_assessment_gets_one_tool_free_retry_over_identical_evidence_without_accepting_bad_fields(self):
        context=self.context();original=json.loads(json.dumps(context))
        for mode in ('field','witness','persistent'):
            calls=[]
            def model(messages,tools):
                payload=json.loads(messages[-1]['content']);calls.append(payload)
                self.assertEqual(tools,[]);self.assertEqual(payload['context'],context)
                self.assertEqual(payload['eligibleEvidenceIDs'],['observed'])
                value=self.review(context)
                if len(calls)==1 or mode=='persistent':
                    if mode=='witness':value['checks'][0]['evidenceIDs']=['forged']
                    else:value['checks'][0]['e4videnceIDs']=value['checks'][0].pop('evidenceIDs')
                if len(calls)==2:
                    self.assertIn('repair',payload)
                    self.assertIn('previousAssessment',payload['repair'])
                return {'choices':[{'message':{'content':json.dumps(value)}}]}
            saved=assess_result(self.brain(model),context,AnswerResult('完整來源與限制',''))
            self.assertEqual(len(calls),2)
            self.assertEqual(saved['status'],'partial' if mode=='persistent' else 'completed')
            self.assertEqual(context,original)
        calls=[]
        def paused_retry(messages,tools):
            calls.append(1)
            if len(calls)==2:raise AutonomyPaused('new human input')
            return {'choices':[{'message':{'content':'{}'}}]}
        with self.assertRaises(AutonomyPaused):assess_result(self.brain(paused_retry),context,AnswerResult('完整來源與限制',''))
        self.assertEqual(len(calls),2)

    def test_known_later_mutation_removes_stale_witness_but_final_snapshot_is_not_an_edit(self):
        context = self.context()
        context['evidence'] = [dict(id='old-test', source='observed', kind='verification', verdict='passed', scopeID='worktree'),
                               dict(id='edit', source='observed', kind='execution', verdict='unknown', scopeID='worktree', invalidatesVerification=True),
                               dict(id='new-test', source='observed', kind='verification', verdict='passed', scopeID='worktree'),
                               dict(id='snapshot', source='observed', kind='artifact', verdict='passed', scopeID='worktree')]
        def model(messages, tools):
            payload = json.loads(messages[-1]['content'])
            self.assertEqual(payload['evidenceOrder'], ['old-test', 'edit', 'new-test', 'snapshot'])
            self.assertEqual(payload['eligibleEvidenceIDs'], ['new-test', 'snapshot'])
            value = self.review(context)
            for check in value['checks']: check['evidenceIDs'] = ['new-test', 'snapshot']
            return {'choices': [{'message': {'content': json.dumps(value)}}]}
        self.assertEqual(assess_result(self.brain(model), context, AnswerResult('完整結果', ''))['status'], 'completed')

    def test_missing_criterion_unknown_or_reported_witness_and_duplicate_json_cannot_close(self):
        context = self.context()
        for edit in (lambda value: value.update(checks=value['checks'][:1]),
                     lambda value: value['checks'][0].update(evidenceIDs=['fabricated']),
                     lambda value: value.update(remaining=['必要工作未完成'])):
            value = self.review(context); edit(value)
            with self.assertRaises(ValueError): validate_assessment(value, context)
        with self.assertRaises(ValueError):
            validate_assessment(self.review(context), {**context, 'evidence': [{**context['evidence'][0], 'source': 'reported'}]})
        raw = json.dumps(self.review(context))[:-1] + ',"status":"completed"}'
        brain = self.brain(lambda *args: {'choices': [{'message': {'content': raw}}]})
        self.assertEqual(assess_result(brain, context, AnswerResult('結果', '摘要'))['status'], 'partial')

    def test_review_cannot_call_tools_and_autonomy_pause_is_propagated(self):
        brain = self.brain(lambda *args: {'choices': [{'message': {'tool_calls': [{'function': {'name': 'execute_command'}}], 'content': '{}'}}]})
        self.assertEqual(assess_result(brain, self.context(), AnswerResult('結果', '摘要'))['status'], 'partial')
        def paused(*args): raise AutonomyPaused('handoff')
        with self.assertRaises(AutonomyPaused): assess_result(self.brain(paused), self.context(), AnswerResult('結果', '摘要'))

    def test_real_registry_receipt_is_copied_at_return_and_keeps_original_requirement_version(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / 'source.txt'; path.write_text('實際來源')
            brain = TaskBrain(SimpleNamespace(), memory=MemoryStore(Path(directory) / 'memory.json'))
            brain._active_input_id = 'human'
            brain._workflow_thread = threading.get_ident()
            reference = dict(taskID='task', inputID='human', requirementsRevision=1, planVersion=1)
            brain._active_workflow_ref = dict(reference)
            adapter = NativeWorkflowToolAdapter(SimpleNamespace(brain=brain))
            brain.tools.result_observer = adapter.observe_tool_result
            body = path.read_text(); payload = dict(root='fixture', path='source.txt', bytes=len(body.encode()), text=body)
            brain.tools.register('read_file', 'actual file reader', {'type': 'object'}, lambda args: payload)
            returned = brain.tools.execute('read_file', {'root': 'fixture', 'path': 'source.txt'})
            returned['text'] = '後來被修改的記憶體物件'
            observation = adapter.observations(reference)[0]
            self.assertEqual(observation['result']['text'], '實際來源')
            self.assertFalse(observation['truncated'])
            self.assertEqual(adapter.observations({**reference, 'requirementsRevision': 2}), [])
            for name in ['recall', 'get_user_profile', 'read_document', 'get_task_status', 'create_task_plan']:
                adapter.observe_tool_result(name, {}, {'private': 'owner-only payload'})
            self.assertEqual(len(adapter.observations(reference)), 1, 'Private tool bodies must not be copied into the common task ledger')
            worker = threading.Thread(target=lambda: brain.tools.execute('read_file', {'root': 'fixture', 'path': 'source.txt'}))
            worker.start(); worker.join()
            self.assertEqual(len(adapter.observations(reference)), 1, 'Another thread must not inherit the active Main input')

    def test_observation_budget_or_unpreservable_result_retains_an_incomplete_marker(self):
        brain = SimpleNamespace(_active_input_id='human', _active_workflow_ref=dict(taskID='task', inputID='human', requirementsRevision=1, planVersion=1),
                                _workflow_observations=[], _workflow_thread=threading.get_ident())
        adapter = NativeWorkflowToolAdapter(SimpleNamespace(brain=brain))
        for index in range(70): adapter.observe_tool_result('read_file', {}, {'text': str(index)})
        receipts = adapter.observations(brain._active_workflow_ref)
        self.assertEqual(len(receipts), 64)
        self.assertEqual(receipts[-1]['tool'], 'workflow_observation_limit')
        self.assertTrue(receipts[-1]['truncated'])
        brain._workflow_observations.clear()
        adapter.observe_tool_result('execute_command', {}, {'stdout': '\ud800'})
        self.assertTrue(adapter.observations(brain._active_workflow_ref)[0]['truncated'])
        brain._workflow_observations.clear()
        adapter.observe_tool_result('read_file', {}, {'text': 'x' * 25000})
        self.assertTrue(adapter.observations(brain._active_workflow_ref)[0]['truncated'])

    def test_actual_foreground_search_registry_records_snippets_with_original_input_scope(self):
        from maltose.agent.taskbrain import TaskBrain, MemoryStore
        from maltose.agent.search import SearchResult
        from maltose.tool_observations import collect_tool_returns
        provider = SimpleNamespace(search=lambda *args, **kwargs: [SearchResult('虛構調查', 'https://example.com/fixture', '測試摘要，不是原始問卷')])
        with tempfile.TemporaryDirectory() as directory:
            brain = TaskBrain(SimpleNamespace(), search_provider=provider, memory=MemoryStore(Path(directory)/'memory.json'))
            brain._active_input_id = 'search-human'
            brain._active_workflow_ref = dict(taskID='task', inputID='search-human', requirementsRevision=1, planVersion=1)
            brain._workflow_thread = threading.get_ident(); brain._workflow_observations = []
            adapter = NativeWorkflowToolAdapter(SimpleNamespace(brain=brain)); brain.tools.result_observer = adapter.observe_tool_result
            with collect_tool_returns() as worker:
                raw = brain.tools.execute('web_search', {'query': '虛構測試'})
            saved = adapter.observations(brain._active_workflow_ref)[0]
            self.assertEqual(saved['tool'], 'web_search')
            self.assertEqual(saved['result']['granularity'], 'search_results')
            self.assertTrue(saved['result']['complete'])
            self.assertEqual(saved['result']['sources'][0]['url'], 'https://example.com/fixture')
            self.assertEqual(worker[0]['result'], saved['result'])
            raw[0]['snippet'] = 'later mutation'
            self.assertEqual(saved['result']['sources'][0]['snippet'], '測試摘要，不是原始問卷')
            self.assertEqual(adapter.observations({**brain._active_workflow_ref, 'inputID': 'another-human'}), [])

    def test_unverified_final_result_does_not_speak_success_and_explicit_read_keeps_review_caveat(self):
        speech = []; work = []; publications = []
        result = AnswerResult('原始模型回報：全部完成。', '全部完成。')
        agent = VoiceAgent(config=AgentConfig(interruptible_tts=False),
            brain=SimpleNamespace(process_result=lambda text, context: work.append(text) or result),
            speaker=SimpleNamespace(synthesize=lambda request: speech.append(request.text)))
        agent.result_handler = lambda result: publications.append(result.result_id) or {
            'chatStored': True, 'workflowAssessment': {'status': 'partial', 'summary': '測試仍未通過。', 'remaining': ['修正失敗測試']}}
        context = TurnContext(user_id='owner', speaker_status='identified', input_source='voice')
        agent._respond_to_input('完成任務', context)
        self.assertTrue(speech)
        self.assertNotIn('全部完成', speech[0])
        self.assertIn('尚未核實', speech[0])
        agent._respond_to_input('念給我聽', context)
        self.assertTrue(speech[-1].startswith('任務仍有待核對事項'))
        self.assertIn(result.full_text, speech[-1])
        self.assertEqual(work, ['完成任務']); self.assertEqual(publications, [result.result_id])


if __name__ == '__main__': unittest.main()
