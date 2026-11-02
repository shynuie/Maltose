"""Verify the configured real model's result format using only public fixtures.

No microphone, playback, private Memory/KDB or task/panel writes are used. Native
delivery and human listening must be verified separately. Report no credentials.
"""
from __future__ import annotations

import argparse
from dataclasses import replace
from datetime import datetime, timezone
import json
from pathlib import Path
import tempfile
import time

from maltose.agent import AgentConfig, VoiceAgent, TurnContext
from maltose.agent.config import load_cli_defaults
from maltose.agent.taskbrain import TaskBrain, MemoryStore, OpenAICompatibleTaskModel
from maltose.presentation import AnswerResult, SpeechPolicy
from maltose.runtime import EventHub
from maltose.runtime.environment import load_private_environment


def verify(config: Path, *, exercise_repair=False, exercise_background_summary=False) -> dict:
    settings = load_cli_defaults(config)
    load_private_environment(config.parent / '.env')
    provider = OpenAICompatibleTaskModel(endpoint=settings['taskbrain_url'], token=settings.get('taskbrain_token'),
        model=settings['taskbrain_model'], timeout=min(settings.get('taskbrain_timeout', 120), 60),
        reasoning_effort=settings.get('taskbrain_reasoning_effort', 'none'))
    class FixtureModel:
        calls = 0
        repair_calls = 0
        finished = False
        def stream(self, messages, tools):
            self.calls += 1
            if 'result_speech_repair:' in messages[0]['content']: self.repair_calls += 1
            yield from provider.stream(messages, [])
            self.finished = True
    model = FixtureModel()
    events = []
    streamed_before_end = []
    hub = EventHub()
    def publish(kind, payload):
        events.append((kind, payload))
        if kind == 'assistant_delta' and not model.finished: streamed_before_end.append(payload['content'])
    hub.publish = publish
    results = []
    prompt = '''這是一個公開、虛構的呈現驗證，請勿查網路或呼叫工具。
請用繁體中文交付一份可閱讀的完整報告：測試資料為甲有3筆、乙有5筆、丙有2筆；
算出總筆數與最大組，並保留各組的表格。包含以下示例連結及原樣程式碼，
連結不是已查核來源：https://example.com/reference
```python
print("Maltose")
```
完整報告至少300字，解釋計算、資料限制、適用範圍及後續真實驗證方法。
必須在完整內容與簡短口頭摘要都說明這是測試資料，不能視為真實研究成果。
將未進行真實來源查核這項限制另外保存在limitations。
'''
    started = time.monotonic()
    with tempfile.TemporaryDirectory(prefix='maltose-result-model-') as temporary:
        memory_path = Path(temporary) / 'memory.json'
        brain = TaskBrain(model, memory=MemoryStore(memory_path))
        agent = VoiceAgent(config=AgentConfig(), brain=brain, voice_enabled=False, event_hub=hub)
        agent.result_handler = lambda result: results.append(result) or {'status': 'not_tested'}
        text, pending, streamed = agent._respond_to_input(prompt, TurnContext(input_source='voice'))
        if len(results) != 1: raise RuntimeError('Expected one validated result')
        result = results[0]
        speech = [payload['content'] for kind, payload in events if kind == 'speech_summary']
        natural_repairs = model.repair_calls
        checks = {
            'structuredResult': result.format_issue is None,
            'completeTextRetained': text == result.display_text and len(result.full_text) >= 300,
            'linkAndCodeRetained': all(value in text for value in ('https://example.com/reference', 'print("Maltose")')),
            'limitationsRetained': bool(result.limitations) and all(item in text for item in result.limitations),
            'summaryContainsTestLimitation': bool(speech) and any(marker in speech[0] for marker in ('測試', '测试', '虛構', '虚构')),
            'summaryWithinBudget': bool(speech) and SpeechPolicy().estimated_seconds(speech[0]) <= 15,
            'textStreamedBeforeCompletion': bool(streamed_before_end),
            'taskExecutedOnce': model.calls - model.repair_calls == 1,
            'atMostOneConditionalSummaryRepair': model.repair_calls <= 1,
            'noPrivateMemoryWrite': not memory_path.exists(),
            'noPendingAudio': pending is None and streamed,
        }
        repair_fixture = None
        if exercise_repair:
            forced = replace(result, spoken_summary='這是虛構測試資料，共10筆，乙組5筆最大，真實來源尚未查核。' * 20)
            before = model.repair_calls
            repaired = brain.repair_spoken_summary(forced, SpeechPolicy())
            selected = SpeechPolicy().choose(repaired, source='voice')
            checks.update({
                'forcedOverBudgetFixture': not SpeechPolicy().summary_is_usable(forced),
                'realRepairWithinBudget': SpeechPolicy().summary_is_usable(repaired) and repaired.spoken_summary != forced.spoken_summary,
                'realRepairPreservesDataLimit': any(marker in selected for marker in ('測試', '测试', '虛構', '虚构'))
                    and any(marker in selected for marker in ('未', '沒有', '没有')),
                'repairLeavesResultAndIdentityUntouched': repaired.full_text == forced.full_text and repaired.result_id == forced.result_id
                    and repaired.limitations == forced.limitations,
                'exactlyOneToolFreeRepairRound': model.repair_calls - before == 1,
                'repairDidNotRepeatTask': model.calls - model.repair_calls == 1,
            })
            repair_fixture = dict(spokenSummary=selected, estimatedSeconds=round(SpeechPolicy().estimated_seconds(selected), 3))
        background_fixture = None
        if exercise_background_summary:
            body = ('公開測試：甲三筆、乙五筆、丙兩筆，共十筆，乙組最多。\n' +
                    '以下各段都是虛構版面測試資料，不增加新的研究事實。\n' * 1000 +
                    '末尾重要限制：未進行任何真實來源查核，不能視為真實研究成果。')
            background = AnswerResult(body, '', kind='partial', limitations=('這是虛構測試資料，原始來源尚未查核。',))
            before = model.repair_calls
            prepared = brain.repair_spoken_summary(background, SpeechPolicy())
            selected = SpeechPolicy().choose(prepared, source='voice')
            checks.update({
                'emptyBackgroundSummaryNeedsRepair': not SpeechPolicy().summary_is_usable(background),
                'backgroundRepairWithinBudget': SpeechPolicy().summary_is_usable(prepared) and bool(prepared.spoken_summary),
                'backgroundDataLimitPreserved': any(marker in selected for marker in ('測試', '测试', '虛構', '虚构'))
                    and any(marker in selected for marker in ('未', '沒有', '没有')),
                'backgroundFullTextAndIdentityPreserved': prepared.full_text == background.full_text and prepared.result_id == background.result_id,
                'oneBackgroundSummaryCall': model.repair_calls - before == 1,
                'backgroundDidNotRepeatTask': model.calls - model.repair_calls == 1,
            })
            background_fixture = dict(inputCharacters=len(body), spokenSummary=selected,
                estimatedSeconds=round(SpeechPolicy().estimated_seconds(selected), 3))
        return dict(schemaVersion=1, checkedAt=datetime.now(timezone.utc).isoformat(),
            model=provider.model, elapsedSeconds=round(time.monotonic()-started, 3),
            status='passed' if all(checks.values()) else 'failed', checks=checks,
            bodyCharacters=len(result.full_text), spokenSummary=speech[0] if speech else '',
            modelSummary=result.spoken_summary, modelCalls=model.calls, summaryRepairCalls=model.repair_calls,
            naturalSummaryRepairCalls=natural_repairs, forcedRepairFixture=repair_fixture,
            backgroundSummaryFixture=background_fixture,
            estimatedSpeechSeconds=round(SpeechPolicy().estimated_seconds(speech[0]), 3) if speech else None,
            microphoneUsed=False, audioPlayed=False, nativePanelsVerified=False)


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--config', type=Path, required=True)
    parser.add_argument('--report', type=Path, required=True)
    parser.add_argument('--exercise-repair', action='store_true', help='Also send one intentionally overlong public summary to the real repair model.')
    parser.add_argument('--exercise-background-summary', action='store_true', help='Verify an empty summary against a complete long public worker result.')
    arguments = parser.parse_args()
    report = verify(arguments.config.expanduser().resolve(), exercise_repair=arguments.exercise_repair,
                    exercise_background_summary=arguments.exercise_background_summary)
    arguments.report.write_text(json.dumps(report, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
    print(json.dumps(report, ensure_ascii=False))
    raise SystemExit(0 if report['status'] == 'passed' else 1)
