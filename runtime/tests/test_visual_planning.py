import io
import json
from pathlib import Path
import tempfile
from types import SimpleNamespace
import unittest

from maltose.agent import TaskStore
from maltose.foreground_results import ForegroundResultService
from maltose.presentation import AnswerResult
from maltose.runtime import EventHub
from maltose.runtime.control import AutonomyPaused
from maltose.ui.native import NativeRuntimeBridge
from maltose.visual_planning import planning_context,construct_chart,select_presentation

DATA='''這是我提供的虛構測試資料；電話與網路方法不同，不能合併成同口徑調查。
日期,機構,甲書%,乙書%,來源
2026-01-01,A,40,35,使用者提供A一月
2026-02-01,B,31,36,使用者提供B二月
2026-03-01,A,42,34,使用者提供A三月
2026-04-01,B,32,38,使用者提供B四月
2026-05-01,A,43,33,使用者提供A五月
2026-06-01,B,34,39,使用者提供B六月
'''
CHOICE=dict(action='chart',tableID='table-1',xColumn='c1',valueColumns=['c3','c4'],groupColumns=['c2'],title='閱讀偏好 (%)',caption='虛構測試資料，不同機構與方法分開；樣本數及誤差未提供。')


class VisualPlanningTests(unittest.TestCase):
    def fixture(self, directory, *, enabled=True):
        store=TaskStore(Path(directory)/'tasks.sqlite3');self.addCleanup(store.close)
        state=dict(model=0,current=True,superseded=False,deliveries=[],calls=[],choice=dict(CHOICE),lost=False,interrupt=False,new=False)
        brain=SimpleNamespace(task_manager=SimpleNamespace(store=store),_active_input_id='human',_active_workflow_ref=None,
            _active_user_id=None,_active_speaker_status='unknown',model=SimpleNamespace(complete=True))
        bridge=SimpleNamespace(brain=brain,conversation_id='conversation',session_id='a'*32,result_chart_version=1,visual_planning_version=1 if enabled else 0,
            workflow=SimpleNamespace(observations=lambda ref:[]),agent=SimpleNamespace(_publish=lambda *args:None))
        service=ForegroundResultService(bridge)
        def model(messages,tools):
            state['model']+=1;self.assertEqual(tools,[])
            rows=store.pending_foreground_results('conversation');self.assertEqual(len(rows),1)
            self.assertIsNone(rows[0]['payload']['result']['chart'],'Save original work before entering presentation model')
            self.assertIsNotNone(store.foreground_presentation(rows[0]['id'],'conversation'))
            self.assertIn('result_visual_planning',messages[0]['content'])
            if state['interrupt']:raise AutonomyPaused('fixture stopped during presentation')
            if state['new']:state.update(current=False,superseded=True)
            if state.get('tool'):return {'choices':[{'message':{'tool_calls':[{'function':{'name':'read_file'}}]}}]}
            return {'choices':[{'message':{'content':json.dumps(state['choice'],ensure_ascii=False)}}]}
        brain._complete_model=model;brain.model.complete=model
        def call(operation,**args):
            state['calls'].append(operation)
            if operation in ('foregroundPresentationCheck','foregroundPrepare'):return dict(current=state['current'],superseded=state['superseded'])
            return {}
        def deliver(result):
            state['deliveries'].append(result)
            if state['lost']:raise TimeoutError('Saved UI may have accepted original ID')
            return dict(chatStored=True,chartStatus='applied' if result.chart else 'none')
        bridge.call_workflow=call;bridge._deliver_result=deliver
        return store,bridge,service,state

    def test_chart_points_and_groups_are_constructed_from_exact_source_rows_not_model_values(self):
        result=AnswerResult('六個月份的完整文字與限制。','摘要')
        context=planning_context(result,DATA,[]);chart=construct_chart(CHOICE,context)
        self.assertEqual(len(chart.series),4);self.assertEqual(len(chart.rows),6)
        self.assertEqual([sorted(v for v in row[1] if v is not None) for row in chart.rows],[[35,40],[31,36],[34,42],[32,38],[33,43],[34,39]])
        self.assertTrue(all(sum(v is None for v in row[1])==2 and '提供' in row[2] for row in chart.rows))
        for edit in (dict(valueColumns=['fake']),dict(groupColumns=[]),dict(values=[99]),dict(tableID='other')):
            with self.assertRaises(ValueError):construct_chart({**CHOICE,**edit},context)

    def test_markdown_missing_values_and_conflicts_do_not_become_invented_zero_or_average(self):
        text='| 月份 | 比例% |\n|---|---:|\n|2026-01|12%|\n|2026-02|—|\n|2026-03|14%|'
        context=planning_context(AnswerResult('完整資料',''),text,[])
        chart=construct_chart({**CHOICE,'valueColumns':['c2'],'groupColumns':[]},context)
        self.assertEqual([row[1] for row in chart.rows],[(12.0,),(None,),(14.0,)])
        self.assertIsNone(planning_context(AnswerResult('資料',''),'日期,比例\n2026-01,12\n2026-02-01,14',[]))
        self.assertIsNone(planning_context(AnswerResult('資料',''),'日期,比例\n2026-01,12%\n2026-02,0.14',[]))
        malformed='日期,比例\n2026-01,12\n2026-02,14\n2026-03,16,extra\n2026-04,18\n2026-05,20'
        self.assertIsNone(planning_context(AnswerResult('資料',''),malformed,[]),'Never accept a prefix of a malformed source block')
        split='日期,比例\n2026-01,12\n2026-02,14\n# 來源中的分隔註記\n2026-03,16\n2026-04,18'
        self.assertIsNone(planning_context(AnswerResult('資料',''),split,[]),'Unparsed later observations cannot disappear from a chart')
        quoted='日期,比例,來源\n2026-01,12,"提供者A|B,原文"\n2026-02,14,"提供者A|B,原文"'
        self.assertIsNotNone(planning_context(AnswerResult('資料',''),quoted,[]))
        scientific=planning_context(AnswerResult('資料',''),'日期,測量\n2026-01,1e-3\n2026-02,2e-3',[])
        self.assertEqual(construct_chart({**CHOICE,'valueColumns':['c2'],'groupColumns':[]},scientific).rows[0][1],(0.001,))
        self.assertIsNone(planning_context(AnswerResult('資料',''),'日期,機構,比例\n2026-01,A,12\n2026-01,B,14',[]))
        conflict=DATA+'2026-01-01,A,90,35,第二個衝突來源\n'
        with self.assertRaises(ValueError):construct_chart(CHOICE,planning_context(AnswerResult('資料',''),conflict,[]))

    def test_only_actual_human_tables_and_complete_public_file_receipts_qualify(self):
        result=AnswerResult(DATA,'')
        self.assertIsNone(planning_context(result,'',[]),'Model prose is not original numeric evidence')
        receipt=dict(root='fixture',path='survey.csv',text=DATA,bytes=len(DATA.encode()))
        for tool in ('web_search','recall','read_document'):
            self.assertIsNone(planning_context(result,'',[dict(tool=tool,result=receipt)]))
        self.assertIsNone(planning_context(result,'',[dict(tool='read_file',result=receipt,truncated=True)]))
        self.assertIsNone(planning_context(result,'',[dict(tool='read_file',result={**receipt,'bytes':1})]))
        self.assertIsNotNone(planning_context(result,'',[dict(tool='read_file',result=receipt,truncated=False)]))

    def test_half_year_chinese_months_normalize_axis_but_preserve_original_evidence(self):
        text = DATA
        for month in range(1, 7):
            text = text.replace(f'2026-{month:02d}-01', f'2026年{month}月')
        context = planning_context(AnswerResult('完整原答案。', ''), text, [])
        chart = construct_chart(CHOICE, context)
        self.assertEqual([row[0] for row in chart.rows], [f'2026-{month:02d}' for month in range(1, 7)])
        self.assertEqual([sorted(v for v in row[1] if v is not None) for row in chart.rows],
                         [[35,40],[31,36],[34,42],[32,38],[33,43],[34,39]])
        for month, row in enumerate(chart.rows, 1):
            self.assertIn(f'日期=2026年{month}月', row[2])
            self.assertEqual(context['tables'][0]['rows'][month-1][0], f'2026年{month}月')
        self.assertEqual(len(chart.series), 4)

    def test_explicit_calendar_dates_sort_chronologically_without_inventing_precision(self):
        choice = {**CHOICE, 'valueColumns':['c2'], 'groupColumns':[]}
        for text, expected in (
            ('日期,比例%\n2026年10月,40\n2026/2,35\n2026-01,30', ['2026-01','2026-02','2026-10']),
            ('日期,比例%\n2026/10/2,40\n2026年2月3日,35\n2026-01-02,30', ['2026-01-02','2026-02-03','2026-10-02']),
            ('日期,比例%\n0001年1月,30\n0001年2月,35', ['0001-01','0001-02']),
        ):
            with self.subTest(text=text):
                context = planning_context(AnswerResult('原答案', ''), text, [])
                self.assertEqual([row[0] for row in construct_chart(choice, context).rows], expected)
        conflicting = '日期,比例%\n2026年1月,40\n2026/1,45\n2026年2月,35'
        with self.assertRaises(ValueError):
            construct_chart(choice, planning_context(AnswerResult('原答案', ''), conflicting, []))
        same = conflicting.replace('2026/1,45', '2026/1,40')
        chart = construct_chart(choice, planning_context(AnswerResult('原答案', ''), same, []))
        self.assertEqual(len(chart.rows), 2)
        self.assertIn('2026年1月', chart.rows[0][2]); self.assertIn('2026/1', chart.rows[0][2])

    def test_ambiguous_or_invalid_dates_cannot_silently_drop_rows_or_acquire_a_year(self):
        for date in ('1月', '01/02', '26年1月', '2026年13月', '2026/2/29',
                     '2026年1月至2月', '2026-01-01至2026-01-07', '2026年1月（預估）'):
            with self.subTest(date=date):
                text = f'日期,比例%\n2026年2月,35\n2026年3月,40\n{date},42'
                self.assertIsNone(planning_context(AnswerResult('原答案', ''), text, []))
        mixed = '日期,比例%\n2026年1月,35\n2026年2月1日,40'
        self.assertIsNone(planning_context(AnswerResult('原答案', ''), mixed, []))

    def test_saved_chinese_month_plan_replays_exact_same_chart_after_disconnect(self):
        text = DATA
        for month in range(1, 7): text = text.replace(f'2026-{month:02d}-01', f'2026年{month}月')
        with tempfile.TemporaryDirectory() as directory:
            store, bridge, service, state = self.fixture(directory)
            result = service.prepare(AnswerResult('保留完整說明與方法限制。', '短摘要'), user_text=text)
            self.assertEqual(result.chart.rows[0][0], '2026-01')
            state['lost'] = True
            self.assertFalse(service.deliver(result.result_id)['workflowStored'])
            store.close()
            reopened = TaskStore(Path(directory)/'tasks.sqlite3'); self.addCleanup(reopened.close)
            bridge.brain.task_manager.store = reopened; bridge.session_id = 'b'*32; state['lost'] = False
            self.assertTrue(ForegroundResultService(bridge).deliver(result.result_id, retry=True)['workflowStored'])
            self.assertEqual(state['model'], 1)
            self.assertEqual(state['deliveries'], [result, result])

    def test_save_original_before_model_seal_view_and_reopen_without_model_tool_or_identity_replay(self):
        with tempfile.TemporaryDirectory() as directory:
            store,bridge,service,state=self.fixture(directory)
            result=service.prepare(AnswerResult('完整答案保留原文。','短摘要'),user_text=DATA)
            self.assertIsNotNone(result.chart);self.assertEqual(state['model'],1)
            self.assertEqual(store.foreground_result(result.result_id,'conversation')['payload']['result']['full_text'],'完整答案保留原文。')
            self.assertIsNone(store.foreground_result(result.result_id,'conversation')['payload']['result']['chart'])
            self.assertEqual(service.prepare(result),result)
            state['lost']=True;self.assertFalse(service.deliver(result.result_id)['workflowStored'])
            store.close();reopened=TaskStore(Path(directory)/'tasks.sqlite3');self.addCleanup(reopened.close)
            bridge.brain.task_manager.store=reopened;bridge.session_id='b'*32;state['lost']=False
            recovered=ForegroundResultService(bridge);receipt=recovered.deliver(result.result_id,retry=True)
            self.assertTrue(receipt['workflowStored']);self.assertFalse(receipt['foregroundSpeechAllowed']);self.assertEqual(state['model'],1)
            self.assertEqual(state['deliveries'],[result,result]);self.assertIsNone(bridge.brain._active_user_id)
            self.assertEqual(reopened._connection.execute('select count(*) from tasks').fetchone()[0],0)
            self.assertEqual(reopened._connection.execute('select count(*) from task_notifications').fetchone()[0],0)
            self.assertEqual(reopened.delivered_foreground_results('conversation',result.result_id)['results'][0]['full_text'],result.display_text)

    def test_crash_during_tool_free_choice_preserves_answer_and_only_repeats_unsaved_presentation(self):
        with tempfile.TemporaryDirectory() as directory:
            store,bridge,service,state=self.fixture(directory);state['interrupt']=True
            with self.assertRaises(AutonomyPaused):service.prepare(AnswerResult('已完成的完整原答案。',''),user_text=DATA)
            row=store.pending_foreground_results('conversation')[0]
            self.assertIsNone(store.foreground_presentation(row['id'],'conversation')['decision'])
            store.close();reopened=TaskStore(Path(directory)/'tasks.sqlite3');self.addCleanup(reopened.close)
            bridge.brain.task_manager.store=reopened;state['interrupt']=False
            # The fixture model observes the same real store after restart.
            bridge.brain._complete_model=lambda messages,tools:{'choices':[{'message':{'content':json.dumps(CHOICE)}}]}
            receipt=ForegroundResultService(bridge).deliver(row['id'],retry=True)
            self.assertTrue(receipt['workflowStored']);self.assertEqual(state['deliveries'][0].full_text,'已完成的完整原答案。')
            self.assertIsNotNone(state['deliveries'][0].chart)

    def test_source_scope_and_sealed_decisions_are_immutable_and_model_cannot_inject_numbers(self):
        with tempfile.TemporaryDirectory() as directory:
            store,bridge,service,state=self.fixture(directory);result=service.prepare(AnswerResult('原答案',''),user_text=DATA)
            plan=store.foreground_presentation(result.result_id,'conversation')
            with self.assertRaises(KeyError):store.foreground_presentation(result.result_id,'another-conversation')
            with self.assertRaises(ValueError):store.prepare_foreground_presentation(result.result_id,'conversation',{**plan['context'],'humanRequest':'changed'})
            changed=json.loads(json.dumps(plan['decision']));changed['chart']['rows'][0]['values'][0]=99
            with self.assertRaises(ValueError):store.save_foreground_presentation(result.result_id,'conversation',changed)
            changed=json.loads(json.dumps(plan['decision']));changed['decision']['caption']='different';changed['chart']['caption']='different'
            with self.assertRaises(ValueError):store.save_foreground_presentation(result.result_id,'conversation',changed)
            self.assertEqual(store.foreground_presentation(result.result_id,'conversation'),plan)

    def test_new_input_before_or_during_choice_blocks_publication_and_keeps_complete_answer(self):
        for during in (False,True):
            with self.subTest(during=during),tempfile.TemporaryDirectory() as directory:
                store,bridge,service,state=self.fixture(directory)
                if during:state['new']=True
                else:state.update(current=False,superseded=True)
                result=service.prepare(AnswerResult('原成果完整保留',''),user_text=DATA)
                service.deliver(result.result_id)
                self.assertEqual(state['model'],int(during));self.assertEqual(state['deliveries'],[])
                self.assertIn('foregroundPrepare',state['calls'],'Superseding a view must not discard the original canonical work report')
                self.assertEqual(store.foreground_result(result.result_id,'conversation')['phase'],'superseded')
                self.assertEqual(store.foreground_result(result.result_id,'conversation')['payload']['result']['full_text'],'原成果完整保留')

    def test_pause_stays_pending_invalid_selection_downgrades_to_text_once_and_capability_zero_skips(self):
        with tempfile.TemporaryDirectory() as directory:
            store,bridge,service,state=self.fixture(directory);state['current']=False
            with self.assertRaises(AutonomyPaused):service.prepare(AnswerResult('原文',''),user_text=DATA)
            result=store.prepared_foreground_answer(store.pending_foreground_results('conversation')[0]['id'],'conversation')
            self.assertEqual(state['model'],0);self.assertEqual(store.foreground_result(result.result_id,'conversation')['phase'],'pending')
            state.update(current=True,tool=True)
            self.assertTrue(service.deliver(result.result_id)['workflowStored'])
            self.assertEqual(state['model'],1);self.assertIsNone(state['deliveries'][0].chart)
        with tempfile.TemporaryDirectory() as directory:
            store,bridge,service,state=self.fixture(directory,enabled=False)
            result=service.prepare(AnswerResult('原文',''),user_text=DATA);service.deliver(result.result_id)
            self.assertEqual(state['model'],0);self.assertNotIn('foregroundPresentationCheck',state['calls'])
            self.assertIsNone(store.foreground_presentation(result.result_id,'conversation'))

    def test_no_chart_choice_honors_human_constraints_and_budget_never_drops_original_body(self):
        with tempfile.TemporaryDirectory() as directory:
            store,bridge,service,state=self.fixture(directory)
            state['choice']=dict(action='text',reason='使用者明確要求只用文字。')
            result=service.prepare(AnswerResult('原答案',''),user_text='只用文字，不要圖表。\n'+DATA)
            self.assertIsNone(result.chart);self.assertIn('不要圖表',store.foreground_presentation(result.result_id,'conversation')['context']['humanRequest'])
        with tempfile.TemporaryDirectory() as directory:
            store,bridge,service,state=self.fixture(directory)
            body='x'*(256*1024-1);result=service.prepare(AnswerResult(body,''),user_text=DATA)
            self.assertEqual(result.full_text,body);self.assertIsNone(result.chart)
            self.assertIn('預算',store.foreground_presentation(result.result_id,'conversation')['decision']['decision']['reason'])

    def test_visual_capability_requires_native_chart_and_durable_foreground_protocols(self):
        base=dict(presentationVersion=1,resultDeliveryVersion=1,resultChartVersion=1,workflowVersion=1,inputScopeVersion=1,foregroundResultVersion=1,visualPlanningVersion=1,conversationID='conversation')
        for change in ({'visualPlanningVersion':True},{'resultChartVersion':0},{'foregroundResultVersion':0}):
            bridge=NativeRuntimeBridge(EventHub(),output_stream=io.StringIO());self.addCleanup(bridge.close)
            with self.assertRaises(ValueError):bridge._dispatch('initialize',{**base,**change})
        bridge=NativeRuntimeBridge(EventHub(),output_stream=io.StringIO());self.addCleanup(bridge.close)
        self.assertEqual(bridge._dispatch('initialize',base)['visualPlanningVersion'],1)
