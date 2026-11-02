from __future__ import annotations
import json
import io
import tempfile
from pathlib import Path
import unittest
import threading
from unittest.mock import patch
from types import SimpleNamespace
from maltose.presentation import AnswerResult, ResultChart, SpeechPolicy, SpeechControl, with_assessment
from maltose.result_stream import ResultTextDecoder, ResultTextDelta
from maltose.agent import AgentConfig, VoiceAgent
from maltose.agent.brain import TurnContext
from maltose.runtime import EventHub
from maltose.ui.native import NativeRuntimeBridge


class PresentationTests(unittest.TestCase):
    def envelope(self, **changes):
        return json.dumps(dict(schemaVersion=1, title='結果', full_text='完整內容', spoken_summary='已完成整理。',
                               kind='answer', visual='auto', limitations=[], **changes), ensure_ascii=False)

    def chart(self):
        return dict(title='測試民調支持度（%）', caption='虛構測試，來源 A；缺月不推估。', xTitle='月份', series=['A — 甲 (%)', 'A — 乙 (%)'],
            rows=[dict(x='2026-01', values=[40, 35], note='使用者提供：測試 A'),
                  dict(x='2026-02', values=[None, None], note='缺少調查'),
                  dict(x='2026-03', values=[42.5, 34], note='使用者提供：測試 A')])

    def test_structured_chart_is_immutable_retained_in_records_and_text_fallback(self):
        chart = self.chart()
        raw = json.loads(self.envelope()); raw['chart'] = chart
        result = AnswerResult.from_json(json.dumps(raw, ensure_ascii=False))
        chart['rows'][0]['values'][0] = 99
        self.assertEqual(result.chart.rows[0][1][0], 40)
        self.assertEqual(result.chart.rows[1][1], (None, None))
        self.assertEqual(AnswerResult.from_record(json.loads(json.dumps(result.to_record()))), result)
        self.assertTrue(result.needs_document)
        self.assertIn('使用者提供：測試 A', result.display_text)
        self.assertIn('| 2026-02 | — | — | 缺少調查 |', result.display_text)
        self.assertNotIn('仍有待確認事項', result.display_text)

    def test_chart_rejects_nonfinite_bool_inconsistent_shapes_and_unlabelled_sources(self):
        for change in ('nan', 'bool', 'shape', 'source', 'series', 'size', 'target'):
            chart = self.chart()
            if change == 'nan': chart['rows'][0]['values'][0] = float('nan')
            elif change == 'bool': chart['rows'][0]['values'][0] = True
            elif change == 'shape': chart['rows'][0]['values'] = [1]
            elif change == 'source': chart['rows'][0]['note'] = ''
            elif change == 'series': chart['series'][1] = chart['series'][0]
            elif change == 'size': chart['rows'] *= 200
            elif change == 'target': chart['panelID'] = 'existing-chart'
            with self.subTest(change=change), self.assertRaises(ValueError): ResultChart.from_dict(chart)

    def test_chart_delivery_requires_actual_chart_ack_and_supports_old_host_text(self):
        bridge = NativeRuntimeBridge(EventHub(), output_stream=io.StringIO()); self.addCleanup(bridge.close)
        bridge.presentation_version = 1; bridge.result_delivery_version = 1; bridge.result_chart_version = 1
        result = AnswerResult('完整結論', '結果為測試資料。', chart=ResultChart.from_dict(self.chart()))
        packets = []
        def deliver(command):
            packets.append(command['deliver_result'])
            return {'ok': True, 'result': dict(publicationID=result.result_id, chatStored=True, panelStatus='applied', panelID='doc', chartStatus='applied', chartPanelID='chart')}
        bridge.call_panel = deliver
        self.assertEqual(bridge.present_result(result)['chartStatus'], 'applied')
        self.assertEqual(packets[0]['chart']['rows'][0]['values'], [40, 35])
        bridge.call_panel = lambda command: {'ok': True, 'result': dict(publicationID=result.result_id, chatStored=True, panelStatus='none')}
        self.assertFalse(bridge.present_result(result)['chatStored'], 'Missing chart ACK must remain unknown, not claim success')
        bridge.result_chart_version = 0
        bridge.call_panel = deliver
        self.assertEqual(bridge.present_result(result)['chartStatus'], 'unsupported')
        self.assertNotIn('chart', packets[-1])
        self.assertIn('圖表資料', packets[-1]['markdown'])

    def test_chart_capability_negotiation_rejects_wrong_versions_and_requires_durable_delivery(self):
        for version in (True, 2, '1'):
            bridge = NativeRuntimeBridge(EventHub(), output_stream=io.StringIO()); self.addCleanup(bridge.close)
            with self.assertRaises(ValueError): bridge._dispatch('initialize', dict(resultChartVersion=version))
        bridge = NativeRuntimeBridge(EventHub(), output_stream=io.StringIO()); self.addCleanup(bridge.close)
        with self.assertRaises(ValueError): bridge._dispatch('initialize', dict(resultChartVersion=1))
        valid = NativeRuntimeBridge(EventHub(), output_stream=io.StringIO()); self.addCleanup(valid.close)
        reply = valid._dispatch('initialize', dict(presentationVersion=1, resultDeliveryVersion=1, resultChartVersion=1))
        self.assertEqual(reply['resultChartVersion'], 1)
        legacy = NativeRuntimeBridge(EventHub(), output_stream=io.StringIO()); self.addCleanup(legacy.close)
        self.assertEqual(legacy._dispatch('initialize', {})['resultChartVersion'], 0)

    def test_data_limits_and_partial_work_do_not_add_a_vague_confirmation_request(self):
        for kind in ('answer', 'partial'):
            result = AnswerResult('完整數據與限制', '甲的支持度上升，但二月沒有調查。', kind=kind, limitations=('二月缺資料',))
            self.assertEqual(SpeechPolicy().choose(result, source='voice'), result.spoken_summary)
        result = AnswerResult('完整發現', '甲的支持度上升。')
        reviewed = with_assessment(result, dict(status='partial', summary='尚缺資料', remaining=['還沒有六月原始問卷。']))
        self.assertIn('甲的支持度上升', reviewed.spoken_summary)
        self.assertIn('六月原始問卷', reviewed.spoken_summary)
        self.assertNotIn('需要你', reviewed.spoken_summary)
        question = with_assessment(result, dict(status='needs_input', remaining=['你要比較政黨支持度還是候選人支持度？']))
        self.assertIn('候選人支持度', question.spoken_summary)
        self.assertEqual(question.kind, 'needs_input')

    def test_separate_content_and_summary_validate_version_duplicates_and_sizes(self):
        result = AnswerResult.from_json(self.envelope())
        self.assertEqual(result.full_text, '完整內容')
        self.assertEqual(result.spoken_summary, '已完成整理。')
        for raw in [self.envelope().replace('"schemaVersion": 1', '"schemaVersion": true'),
                    self.envelope()[:-1]+',"title":"different"}',
                    self.envelope().replace('"limitations": []', '"limitations": "hidden"')]:
            with self.assertRaises(ValueError): AnswerResult.from_json(raw)
        with self.assertRaises(ValueError): AnswerResult('x' * (256 * 1024 + 1), 'short')
        with self.assertRaises(ValueError): AnswerResult('answer', '', kind='completed')

    def test_default_speech_does_not_read_urls_code_or_entire_long_answer(self):
        long = AnswerResult('詳細內容\n' * 200 + '\nhttps://example.com/source', '找到三個重點，還有一項尚未確認。')
        policy = SpeechPolicy()
        self.assertEqual(policy.choose(long, source='voice'), long.spoken_summary)
        self.assertEqual(policy.choose(long, source='native'), '')
        self.assertEqual(policy.choose(long, source='web'), '')
        self.assertTrue(long.needs_document)
        unsafe = AnswerResult('full code ```python\npass\n```', 'See https://example.com/source')
        self.assertNotIn('https://', policy.choose(unsafe, source='voice'))
        oversized = AnswerResult('full answer', '這是過長的語音。' * 50)
        self.assertLessEqual(policy.estimated_seconds(policy.choose(oversized, source='voice')), 15)
        self.assertEqual(policy.choose(long, source='voice', mode='read'), long.full_text)

    def test_compatibility_failure_preserves_complete_body_without_reading_json(self):
        result = AnswerResult.from_legacy('{"full_text":"保留完整內容","bad":true}', format_issue='invalid')
        self.assertEqual(result.full_text, '保留完整內容')
        self.assertEqual(result.kind, 'partial')
        self.assertNotIn('{', SpeechPolicy().choose(result, source='voice'))

    def test_native_delivery_failure_keeps_chat_and_never_retries_publication(self):
        bridge = NativeRuntimeBridge(EventHub())
        bridge.presentation_version = 1
        calls = []
        def fail(command): calls.append(command); raise TimeoutError('unknown')
        bridge.call_panel = fail
        result = AnswerResult('body ' * 100, '短摘要')
        self.assertEqual(bridge.present_result(result)['status'], 'panel_unknown')
        self.assertEqual(len(calls), 1)
        self.assertEqual(calls[0]['publish_document']['publicationID'], result.result_id)

    def test_voice_path_preserves_complete_chat_and_speaks_only_summary(self):
        class Speaker:
            def __init__(self): self.texts = []
            def synthesize(self, request): self.texts.append(request.text)
        result = AnswerResult('完整內容\n' * 100, '結果仍有一項待確認。', kind='partial')
        brain = SimpleNamespace(process_result=lambda text, context: result)
        speaker = Speaker(); hub = EventHub(); events = []
        original = hub.publish
        def publish(kind, payload): events.append((kind, payload)); return original(kind, payload)
        hub.publish = publish
        agent = VoiceAgent(config=AgentConfig(interruptible_tts=False), brain=brain, speaker=speaker, event_hub=hub)
        agent.result_handler = lambda value: {'status': 'panel_failed'}
        text, pending, streamed = agent._respond_to_input('請整理', TurnContext(input_source='voice'))
        self.assertEqual(text, result.full_text); self.assertIsNone(pending); self.assertTrue(streamed)
        self.assertEqual(speaker.texts, [SpeechPolicy().choose(result, source='voice')])
        self.assertEqual([data['content'] for kind, data in events if kind=='assistant_end'], [result.full_text])
        speaker.texts.clear()
        agent._respond_to_input('鍵盤問題', TurnContext(input_source='native'))
        self.assertEqual(speaker.texts, [])

    def test_publication_requires_valid_panel_receipt_before_claiming_applied(self):
        bridge = NativeRuntimeBridge(EventHub())
        self.addCleanup(bridge.close)
        bridge.presentation_version = 1
        result = AnswerResult('long ' * 100, '摘要')
        for receipt in ({}, {'result': {}}, {'result': None}, {'result': {'panelID': ''}}, {'result': {'panelID': 'bad\nid'}}):
            bridge.call_panel = lambda command, value=receipt: {'ok': True, **value}
            self.assertEqual(bridge.present_result(result)['status'], 'panel_unknown')
        panel_id = '文檔-234962e9-ac6c-4240-85cc-0525339b4606'
        bridge.call_panel = lambda command: {'ok': True, 'result': {'panelID': panel_id}}
        self.assertEqual(bridge.present_result(result), {'status': 'panel_applied', 'panelID': panel_id})

    def test_taskbrain_single_completion_produces_typed_result_without_extra_model_call(self):
        from maltose.agent.taskbrain import TaskBrain, MemoryStore
        class Model:
            def __init__(self, raw): self.raw = raw; self.calls = []
            def complete(self, messages, tools):
                self.calls.append(messages)
                return {'choices': [{'message': {'content': self.raw}}]}
        with tempfile.TemporaryDirectory() as directory:
            model = Model(self.envelope())
            brain = TaskBrain(model, memory=MemoryStore(Path(directory)/'memory.json'))
            result = brain.process_result('請回答', TurnContext(input_source='native'))
            self.assertEqual(result.full_text, '完整內容')
            self.assertEqual(len(model.calls), 1)
            self.assertIn('spoken_summary', model.calls[0][0]['content'])
            self.assertFalse((Path(directory)/'memory.json').exists())
            model.raw = '相容回答'
            fallback = brain.process_result('下一個問題', TurnContext(input_source='native'))
            self.assertEqual(fallback.full_text, '相容回答')
            self.assertEqual(fallback.format_issue, 'invalid_result_format')

    def test_limitations_and_failure_survive_speech_budget_and_display(self):
        result = AnswerResult('收集到的內容', '完成。', kind='failed', limitations=('來源尚未核對',))
        self.assertIn('來源尚未核對', result.display_text)
        self.assertIn('未成功', SpeechPolicy().choose(result, source='voice'))
        excessive = AnswerResult('完整內容', '超長。' * 100, kind='partial')
        self.assertIn('無法可靠精簡', SpeechPolicy().choose(excessive, source='voice'))
        with self.assertRaises(ValueError): AnswerResult('valid', '', title='bad\nheading')
        for kind in ('partial', 'failed'):
            missing = AnswerResult('完整長內容。' * 100, '', kind=kind, limitations=('尚未核對',))
            self.assertFalse(SpeechPolicy().summary_is_usable(missing), 'A failure/limitation cue alone cannot replace the result summary')

    def test_stream_only_model_keeps_tool_loop_and_uses_only_final_content(self):
        from maltose.agent.taskbrain import TaskBrain, MemoryStore, ToolRegistry
        tools = ToolRegistry(); calls = []
        tools.register('fixture', 'test only', {'type': 'object', 'properties': {}}, lambda args: calls.append(args) or {'ok': True})
        final = self.envelope()
        class StreamOnly:
            def __init__(self): self.calls = 0
            def stream(self, messages, schemas):
                self.calls += 1
                if self.calls == 1:
                    yield {'choices': [{'delta': {'content': '工具前的說明。', 'tool_calls': [{'index': 0, 'id': 'fixture-1',
                        'function': {'name': 'fixture', 'arguments': '{}'}}]}}]}
                else:
                    yield {'choices': [{'delta': {'content': final}}]}
        with tempfile.TemporaryDirectory() as directory:
            model = StreamOnly()
            brain = TaskBrain(model, tools=tools, memory=MemoryStore(Path(directory)/'memory.json'))
            result = brain.process_result('請整理')
            self.assertEqual(result.full_text, '完整內容')
            self.assertIsNone(result.format_issue)
            self.assertEqual(model.calls, 2)
            self.assertEqual(calls, [{}])

    def test_presentation_negotiation_keeps_old_clients_on_legacy_path(self):
        result = AnswerResult('long ' * 100, '短摘要')
        for version in (None, 1, True, 2):
            with self.subTest(version=version):
                output = io.StringIO()
                bridge = NativeRuntimeBridge(EventHub(), output_stream=output)
                self.addCleanup(bridge.close)
                params = {} if version is None else {'presentationVersion': version}
                bridge.receive_line(json.dumps({'schemaVersion': 1, 'requestID': 'init', 'method': 'initialize', 'params': params}))
                response = json.loads(output.getvalue().splitlines()[-1])
                if version is None:
                    self.assertTrue(response['ok']); self.assertEqual(bridge.presentation_version, 0)
                    bridge.call_panel = lambda *args: self.fail('Old client must not receive an unknown panel command')
                    self.assertEqual(bridge.present_result(result)['status'], 'panel_unavailable')
                elif type(version) is int and version == 1:
                    self.assertTrue(response['ok']); self.assertEqual(response['result']['presentationVersion'], 1)
                else:
                    self.assertFalse(response['ok']); self.assertEqual(bridge.presentation_version, 0)

    def test_stream_decoder_handles_every_split_and_only_top_level_full_text(self):
        body = '第一行\n"引號"、反斜線\\與emoji😀\t完成。'
        raw = json.dumps({'nested': {'full_text': '不能外洩的巢狀值'}, 'schemaVersion': 1, 'full_text': body,
                          'spoken_summary': '不應混入全文'}, ensure_ascii=True)
        for boundary in range(len(raw) + 1):
            decoder = ResultTextDecoder()
            self.assertEqual(decoder.feed(raw[:boundary]) + decoder.feed(raw[boundary:]), body, boundary)
        decoder = ResultTextDecoder()
        self.assertEqual(''.join(decoder.feed(character) for character in raw), body)
        for malformed in ('plain text', '{"full_text":42}', '{"full_text":"bad\\q"}'):
            decoder = ResultTextDecoder()
            decoded = ''.join(decoder.feed(character) for character in malformed)
            self.assertNotIn('full_text', decoded)
        decoder = ResultTextDecoder()
        decoder.maximum_bytes = 4
        self.assertEqual(decoder.feed(raw), '')

    def test_complete_text_arrives_before_model_finishes_and_summary_only_after(self):
        from maltose.agent.taskbrain import TaskBrain, MemoryStore
        speaker_texts = []
        events = []
        hub = EventHub()
        hub.publish = lambda kind, payload: events.append((kind, payload))
        raw = self.envelope().replace('完整內容', '完整內容第一段\\n第二段')
        split = raw.index('第二段')
        class Model:
            def stream(self, messages, tools):
                yield {'choices': [{'delta': {'content': raw[:split]}}]}
                self_has_draft = [p['content'] for kind, p in events if kind == 'assistant_delta']
                if self_has_draft != ['完整內容第一段\n']:
                    raise AssertionError(self_has_draft)
                if speaker_texts: raise AssertionError('Draft or envelope was sent to TTS')
                yield {'choices': [{'delta': {'content': raw[split:]}}]}
        with tempfile.TemporaryDirectory() as directory:
            brain = TaskBrain(Model(), memory=MemoryStore(Path(directory)/'memory.json'))
            agent = VoiceAgent(config=AgentConfig(interruptible_tts=False), brain=brain,
                               speaker=SimpleNamespace(synthesize=lambda request: speaker_texts.append(request.text)), event_hub=hub)
            agent.result_handler = lambda result: {'status': 'chat_only'}
            result, _, _ = agent._respond_to_input('回答', TurnContext(input_source='voice'))
        self.assertEqual(result, '完整內容第一段\n第二段')
        self.assertEqual(speaker_texts, ['已完成整理。'])
        self.assertEqual([p['content'] for k, p in events if k == 'assistant_end'], [result])
        self.assertNotIn('schemaVersion', ''.join(p['content'] for k, p in events if k == 'assistant_delta'))

    def test_tool_round_draft_is_reset_and_final_result_is_authoritative(self):
        from maltose.agent.taskbrain import TaskBrain, MemoryStore, ToolRegistry
        calls = []
        tools = ToolRegistry()
        tools.register('fixture', 'test', {'type': 'object', 'properties': {}}, lambda args: calls.append(args) or {})
        raw = self.envelope()
        class Model:
            def __init__(self): self.round = 0
            def stream(self, messages, schemas):
                self.round += 1
                if self.round == 1:
                    yield {'choices': [{'delta': {'content': '{"full_text":"工具前草稿"}', 'tool_calls': [
                        {'index': 0, 'id': 'fixture', 'function': {'name': 'fixture', 'arguments': '{}'}}]}}]}
                else: yield {'choices': [{'delta': {'content': raw}}]}
        with tempfile.TemporaryDirectory() as directory:
            brain = TaskBrain(Model(), tools=tools, memory=MemoryStore(Path(directory)/'memory.json'))
            stream = brain.process_result_stream('測試')
            deltas = []
            while True:
                try: deltas.append(next(stream))
                except StopIteration as done:
                    final = done.value
                    break
        self.assertEqual(deltas, [ResultTextDelta('工具前草稿'), ResultTextDelta(reset=True), ResultTextDelta('完整內容')])
        self.assertEqual(final.full_text, '完整內容')
        self.assertEqual(calls, [{}])

    def test_local_read_and_mute_controls_preserve_preference_and_do_not_repeat_work(self):
        calls = []; publications = []; speech = []
        result = AnswerResult('全文\n' * 100, '短摘要')
        agent = VoiceAgent(config=AgentConfig(interruptible_tts=False, speech_mode='mute'),
                           brain=SimpleNamespace(process_result=lambda text, context: calls.append(text) or result),
                           speaker=SimpleNamespace(synthesize=lambda request: speech.append(request.text)))
        agent.result_handler = lambda value: publications.append(value.result_id) or {'status': 'chat_only'}
        context = TurnContext(input_source='native')
        agent._respond_to_input('整理資料', context)
        self.assertEqual(speech, [])
        agent._respond_to_input('念給我聽', context)
        self.assertEqual(speech, [result.display_text])
        self.assertEqual(calls, ['整理資料'])
        self.assertEqual(publications, [result.result_id])
        agent._respond_to_input('先別說話：整理另一份資料', context)
        self.assertEqual(len(speech), 1)
        self.assertEqual(calls[-1], '整理另一份資料')
        agent._respond_to_input('先別說話', context)
        self.assertEqual(len(calls), 2)
        self.assertEqual(agent.config.speech_mode, 'mute')
        agent._respond_to_input('念給我聽', TurnContext(user_id='someone', speaker_status='identified', input_source='voice'))
        self.assertEqual(len(speech), 1, 'A different speaker/source cannot replay cached private results')
        agent._end_brain_session()
        agent._respond_to_input('念給我聽', context)
        self.assertEqual(len(speech), 1)
        self.assertEqual(SpeechControl.parse('請說明「念給我聽」這個功能').mode, None)
        self.assertEqual(SpeechControl.parse('詳細說').mode, 'read')

    def test_saved_speech_preference_loads_and_invalid_values_fail_before_startup(self):
        from maltose.agent.config import load_cli_defaults
        from maltose.agent.cli import build_parser
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory)/'maltose.toml'
            path.write_text('[presentation]\nspeech_mode="summary"\nspeech_target_seconds=12\n', encoding='utf-8')
            parser = build_parser()
            parser.set_defaults(**load_cli_defaults(path))
            args = parser.parse_args([])
            config = AgentConfig(speech_mode=args.speech_mode, speech_target_seconds=args.speech_target_seconds)
        result = AnswerResult('內容', '簡短摘要')
        self.assertEqual(SpeechPolicy(target_seconds=config.speech_target_seconds).choose(result, source='native', mode=config.speech_mode), '簡短摘要')
        for mode, seconds in [('read', 15), ('bad', 15), ('auto', float('nan')), ('auto', True), ('auto', 31)]:
            with self.assertRaises(ValueError): AgentConfig(speech_mode=mode, speech_target_seconds=seconds)

    def test_failed_delivery_and_failed_speech_preserve_chat_without_repeating_model(self):
        events = []; calls = []
        hub = EventHub()
        hub.publish = lambda kind, payload: events.append((kind, payload))
        result = AnswerResult('全文\n' * 100, '摘要')
        def fail(*args): raise RuntimeError('fixture failure')
        agent = VoiceAgent(config=AgentConfig(interruptible_tts=False), event_hub=hub,
                           brain=SimpleNamespace(process_result=lambda text, context: calls.append(text) or result),
                           speaker=SimpleNamespace(synthesize=fail))
        agent.result_handler = fail
        text, _, _ = agent._respond_to_input('工作', TurnContext(input_source='voice'))
        self.assertEqual(text, result.full_text)
        self.assertEqual(calls, ['工作'])
        self.assertEqual([data['status'] for kind, data in events if kind == 'result_presentation'], ['panel_unknown'])
        self.assertEqual([data['result_id'] for kind, data in events if kind == 'speech_failed'], [result.result_id])

    def test_new_input_suppresses_pending_summary_but_keeps_complete_result(self):
        entered = threading.Event(); release = threading.Event()
        speech = []; events = []; publications = []
        result = AnswerResult('已取得的完整結果', '摘要')
        def process(text, context):
            entered.set()
            if not release.wait(2): raise TimeoutError('fixture did not release')
            return result
        hub = EventHub(); hub.publish = lambda kind, payload: events.append((kind, payload))
        agent = VoiceAgent(config=AgentConfig(interruptible_tts=False), event_hub=hub,
                           brain=SimpleNamespace(process_result=process),
                           speaker=SimpleNamespace(synthesize=lambda request: speech.append(request.text)))
        agent.result_handler = lambda value: publications.append(value.result_id) or {'status': 'chat_only'}
        thread = threading.Thread(target=lambda: agent._respond_to_input('舊需求', TurnContext(input_source='voice')))
        thread.start()
        try:
            self.assertTrue(entered.wait(1))
            agent.submit_text('追加要求', source='native')
        finally:
            release.set(); thread.join(2)
        self.assertFalse(thread.is_alive())
        self.assertEqual(speech, [])
        self.assertEqual(publications, [result.result_id])
        self.assertEqual([p['content'] for k, p in events if k == 'assistant_end'], [result.full_text])
        self.assertTrue(any(k == 'speech_cancelled' for k, _ in events))

    def test_new_input_stops_long_read_and_no_remaining_segments_are_played(self):
        started = threading.Event(); stopped = threading.Event(); requests = []
        class Speaker:
            def synthesize(self, request):
                requests.append(request)
                started.set()
                if not stopped.wait(2): raise TimeoutError('Speech did not stop')
            def stop(self): stopped.set()
        agent = VoiceAgent(config=AgentConfig(interruptible_tts=False), speaker=Speaker())
        result = AnswerResult('長文' * 1000, '摘要')
        thread = threading.Thread(target=lambda: agent._speak_result(result, source='native', mode='read'))
        thread.start()
        try:
            self.assertTrue(started.wait(1))
            agent.submit_text('先別說話', source='native')
        finally:
            stopped.set(); thread.join(2)
        self.assertFalse(thread.is_alive())
        self.assertEqual(len(requests), 1)
        self.assertLessEqual(len(requests[0].text), 600)
        self.assertTrue(requests[0].cancel_event.is_set())

    def test_cancelled_speech_request_never_launches_macOS_player(self):
        from maltose.voice import MacOSSayTTS, TTSRequest
        cancel = threading.Event(); cancel.set()
        with patch('maltose.voice.tts.platform.system', return_value='Darwin'), patch('maltose.voice.tts.subprocess.Popen') as launch:
            MacOSSayTTS().synthesize(TTSRequest('過期語音', cancel_event=cancel))
        launch.assert_not_called()

    def test_only_unusable_voice_summary_is_repaired_without_repeating_task_or_text(self):
        from maltose.agent.taskbrain import TaskBrain, MemoryStore
        events = []; speech = []; publications = []
        raw = json.loads(self.envelope())
        raw.update(full_text='測試資料的完整內容。' * 100, spoken_summary='測試資料尚未查核。' * 20, limitations=['僅為測試資料'])
        class Model:
            def __init__(self): self.task_calls = 0; self.repair_calls = 0
            def stream(self, messages, tools):
                if 'result_speech_repair:' in messages[0]['content']:
                    self.repair_calls += 1
                    if tools: raise AssertionError('Summary repair must not operate tools')
                    if not any(kind == 'assistant_end' for kind, _ in events): raise AssertionError('Full text must not wait for summary repair')
                    content = '{"spoken_summary":"測試資料共十筆，真實來源仍未查核。"}'
                else:
                    self.task_calls += 1
                    content = json.dumps(raw, ensure_ascii=False)
                yield {'choices': [{'delta': {'content': content}}]}
        hub = EventHub(); hub.publish = lambda kind, payload: events.append((kind, payload))
        with tempfile.TemporaryDirectory() as directory:
            model = Model()
            brain = TaskBrain(model, memory=MemoryStore(Path(directory)/'memory.json'))
            agent = VoiceAgent(config=AgentConfig(interruptible_tts=False), brain=brain, event_hub=hub,
                               speaker=SimpleNamespace(synthesize=lambda request: speech.append(request.text)))
            agent.result_handler = lambda value: publications.append(value) or {'status': 'chat_only'}
            text, _, _ = agent._respond_to_input('測試', TurnContext(input_source='voice'))
            self.assertEqual(model.task_calls, 1); self.assertEqual(model.repair_calls, 1)
            self.assertEqual(text, publications[0].display_text)
            self.assertIn('測試資料', speech[0]); self.assertIn('未查核', speech[0])
            self.assertLessEqual(SpeechPolicy().estimated_seconds(speech[0]), 15)
            self.assertEqual(agent._last_result.result_id, publications[0].result_id)
            self.assertEqual(agent._last_result.full_text, publications[0].full_text)
            agent._respond_to_input('鍵盤輸入', TurnContext(input_source='native'))
            self.assertEqual(model.task_calls, 2); self.assertEqual(model.repair_calls, 1, 'Silent input needs no summary model call')

    def test_summary_repair_rejects_invalid_format_and_does_not_loop_or_change_result(self):
        from maltose.agent.taskbrain import TaskBrain, MemoryStore
        class Model:
            def __init__(self): self.calls = 0
            def complete(self, messages, tools):
                self.calls += 1
                return {'choices': [{'message': {'content': '{"spoken_summary":"短摘要","spoken_summary":"重複"}'}}]}
        with tempfile.TemporaryDirectory() as directory:
            model = Model()
            brain = TaskBrain(model, memory=MemoryStore(Path(directory)/'memory.json'))
            result = AnswerResult('完整結果', '過長。' * 100, limitations=('未完成查核',))
            with self.assertLogs('maltose.agent.taskbrain', level='WARNING'):
                repaired = brain.repair_spoken_summary(result, SpeechPolicy())
            self.assertIs(repaired, result)
            self.assertEqual(model.calls, 1)
            valid = AnswerResult('完整結果', '簡短摘要')
            self.assertIs(brain.repair_spoken_summary(valid, SpeechPolicy()), valid)
            self.assertEqual(model.calls, 1)

    def test_mute_and_pending_human_input_also_protect_legacy_background_notification_path(self):
        speech = []; events = []; drains = []
        def notifications(): drains.append(True); return ['背景工作回報，保留文字。']
        hub = EventHub(); hub.publish = lambda kind, payload: events.append((kind, payload))
        agent = VoiceAgent(config=AgentConfig(interruptible_tts=False), event_hub=hub,
            brain=SimpleNamespace(process_result=lambda text, context: AnswerResult('答覆', '短摘要'), consume_task_notifications=notifications),
            speaker=SimpleNamespace(synthesize=lambda request: speech.append(request.text)))
        agent.result_handler = lambda value: {'status': 'chat_only'}
        agent._respond_to_input('先別說話', TurnContext(input_source='voice'))
        agent._speak_task_notifications()
        self.assertEqual(speech, [])
        self.assertTrue(any(p.get('content') == '背景工作回報，保留文字。' for _, p in events))
        agent.submit_text('新的要求', source='native')
        agent._speak_task_notifications()
        self.assertEqual(len(drains), 1, 'Do not remove notifications before pending human input is handled')
