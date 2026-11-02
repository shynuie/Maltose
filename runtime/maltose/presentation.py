"""Versioned final-answer content, independent of task success and delivery.

This contract does not grant panel-write or personal-data permissions. The host
owns publication IDs and acknowledges actual panel delivery separately.
"""
from __future__ import annotations
from dataclasses import dataclass, field
import json
import re
import uuid

RESULT_FORMAT_INSTRUCTIONS = '''
Return the final answer as one JSON object, without code fences, with exactly:
{"schemaVersion":1,"title":"short title in the user's language","full_text":"complete answer, including Markdown, URLs, code and detail where useful","spoken_summary":"one or two short plain-language sentences, roughly 10 seconds","kind":"answer","visual":"auto","limitations":[]}.
kind is answer, partial, needs_input or failed; visual is auto, document or none.
You may add one optional chart field (otherwise omit it or set null):
{"title":"short descriptive chart title with unit","caption":"visible source/method caveat, not a claim of completion","xTitle":"Date","series":["Source A — item (%)"],"rows":[{"x":"2026-01-01","values":[42.5],"note":"source URL or user-provided data; survey dates/method if known"},{"x":"2026-02-01","values":[null],"note":"no observation; leave a gap"},{"x":"2026-03-01","values":[40],"note":"source URL or user-provided data"}]}.
AUTONOMOUS PRESENTATION: When your answer contains several actual dated numeric
observations (polls, prices, measurements, monthly comparisons), proactively add
a chart without waiting for the user to request one. The host creates a NEW native
interactive chart alongside the full answer. The chart field always creates new
panels and cannot update existing ones. You have standing permission to operate
existing panels without asking for authorization or speaker verification. When
reusing or updating a chart is useful, use its panel tools and omit chart to avoid
a duplicate. Prefer a new panel for a new result and obey explicit instructions
to preserve existing content. Local-file writes/deletions retain filesystem permissions. Do not substitute Mermaid, ASCII,
SVG, or a promise to draw later. This final chart field does not cost a tool call.
If the complete dataset exceeds chart limits, choose a clearly described comparable
subset for the chart and preserve all other data in full_text; never silently omit it.
Chart limits: 1–8 distinct series, 2–366 rows, finite numbers or null only, exactly
one value per series in every row; every point retains its source/method in note.
Keep dates in chronological order. Use exact dates only when known, otherwise
retain the supplied month/date label. Keep numerical units consistent within a
chart. Preserve missing values as null; never infer, interpolate, invent or replace
missing data with zero. Do not mix different pollsters/methods/questions in one
continuous series: separate them by series, leaving null where not observed.
If only fragments/search snippets are available, label that limitation and do not
invent full survey metadata or a complete six-month dataset. Retain source links,
underlying values and qualifications in full_text as well as the point notes.
If too few comparable numeric observations exist, explain the exact missing data
in full_text rather than fabricating a chart or asking for permission to present
already available data. Only ask the human when their decision is truly necessary.
Data limitations do not imply a pending human confirmation. A needs_input result
must contain the concrete question; partial must say exactly what is missing.
Avoid vague phrases such as 'still needs confirmation' without naming the issue.
These final-output instructions override prose-only voice formatting: full_text
may use Markdown. Aim for at most 35 Chinese characters or 25 English words in
spoken_summary, preserving the main conclusion and important
limitations, contain no URLs, code, paths or long lists, and make no claims about
panels being created/displayed or audio being heard. The host handles presentation.
Do not shorten full_text to match speech. Do not declare a product task complete
just because a tool/worker returned. The host verifies task completion separately.
Do not call panel tools merely to duplicate this final answer in a document.
When the user requests a new document containing a plan, report or answer, put
that COMPLETE content in full_text and set visual=document. This is the supported
publication path: the host creates the new result document after receiving your
answer. Do not first create an empty document with panel tools. Document panels
are not notes panels; notes_set_text cannot populate a document. Even if any
panel/tool presentation attempt fails, keep the entire useful result in
full_text, together with its limitations, rather than only a summary of the
missing content or a failure notice.
'''


@dataclass(frozen=True)
class ResultChart:
    title: str
    caption: str
    xTitle: str
    series: tuple[str, ...]
    rows: tuple[tuple[str, tuple[float | None, ...], str], ...]

    @classmethod
    def from_dict(cls, value):
        import math
        if not isinstance(value, dict) or set(value) != {'title', 'caption', 'xTitle', 'series', 'rows'}:
            raise ValueError('Invalid chart fields')
        def text(v, size):
            return isinstance(v, str) and bool(v.strip()) and len(v.encode('utf-8')) <= size and not any(ord(c) < 32 for c in v)
        if not all(text(value[k], n) for k, n in [('title', 200), ('caption', 2000), ('xTitle', 100)]):
            raise ValueError('Invalid chart labels')
        series, rows = value['series'], value['rows']
        if not isinstance(series, list) or not 1 <= len(series) <= 8 or not all(text(v, 200) for v in series) or len(set(series)) != len(series):
            raise ValueError('Invalid chart series')
        if not isinstance(rows, list) or not 2 <= len(rows) <= 366: raise ValueError('Invalid chart rows')
        def finite(v):
            try: return type(v) in (int, float) and math.isfinite(v)
            except OverflowError: return False
        saved = []; count = 0
        for row in rows:
            if not isinstance(row, dict) or set(row) != {'x', 'values', 'note'} or not text(row['x'], 100) or not text(row['note'], 2000):
                raise ValueError('Chart points require a label and source/note')
            values = row['values']
            if not isinstance(values, list) or len(values) != len(series) or any(v is not None and not finite(v) for v in values):
                raise ValueError('Invalid chart numbers')
            count += sum(v is not None for v in values)
            saved.append((row['x'], tuple(values), row['note']))
        if count < 2 or len(json.dumps(value, ensure_ascii=False).encode()) > 128 * 1024: raise ValueError('Insufficient or oversized chart')
        return cls(value['title'], value['caption'], value['xTitle'], tuple(series), tuple(saved))

    def to_dict(self):
        return dict(title=self.title, caption=self.caption, xTitle=self.xTitle, series=list(self.series),
                    rows=[dict(x=x, values=list(values), note=note) for x, values, note in self.rows])


@dataclass(frozen=True)
class AnswerResult:
    full_text: str
    spoken_summary: str
    title: str = 'Maltose 結果'
    kind: str = 'answer'
    visual: str = 'auto'
    limitations: tuple[str, ...] = ()
    result_id: str = field(default_factory=lambda: uuid.uuid4().hex)
    format_issue: str | None = None
    chat_message_id: str | None = None
    workflow_ref: dict | None = None
    delivery_origin: str = 'main'
    chart: ResultChart | None = None

    def __post_init__(self):
        if self.chart is not None:
            if not isinstance(self.chart, ResultChart): raise ValueError('Invalid result chart')
            ResultChart.from_dict(self.chart.to_dict())
        for value, maximum, required in ((self.full_text, 256 * 1024, True),
                                         (self.spoken_summary, 4096, False), (self.title, 200, True)):
            if not isinstance(value, str) or len(value.encode('utf-8')) > maximum or (required and not value.strip()):
                raise ValueError('Invalid result text or size')
        if any(ord(character) < 32 for character in self.title): raise ValueError('Invalid title control characters')
        if not isinstance(self.kind, str) or not isinstance(self.visual, str) or self.kind not in {'answer', 'partial', 'needs_input', 'failed'} or self.visual not in {'auto', 'document', 'none'}:
            raise ValueError('Invalid result classification')
        if not isinstance(self.limitations, tuple) or len(self.limitations) > 12 or any(
                not isinstance(item, str) or not 1 <= len(item) <= 1000 for item in self.limitations):
            raise ValueError('Invalid result limitations')
        if not isinstance(self.result_id, str) or not re.fullmatch(r'[A-Za-z0-9._:-]{1,128}', self.result_id):
            raise ValueError('Invalid result ID')
        if self.chat_message_id is not None and (not isinstance(self.chat_message_id, str) or not re.fullmatch(r'[A-Za-z0-9._:-]{1,128}', self.chat_message_id)):
            raise ValueError('Invalid chat message ID')
        if self.workflow_ref is not None and (not isinstance(self.workflow_ref, dict) or len(json.dumps(self.workflow_ref).encode()) > 4096):
            raise ValueError('Invalid runtime workflow reference')
        if len(self.display_text.encode('utf-8')) > 256 * 1024: raise ValueError('Rendered result exceeds delivery size')
        if not isinstance(self.delivery_origin, str) or self.delivery_origin not in {'main', 'background'}: raise ValueError('Invalid runtime delivery origin')

    def to_record(self) -> dict:
        from dataclasses import asdict
        value = {'schemaVersion': 1, **asdict(self)}
        value['chart'] = self.chart.to_dict() if self.chart else None
        return value

    @classmethod
    def from_record(cls, record: dict) -> 'AnswerResult':
        value = dict(record)
        if type(value.pop('schemaVersion', None)) is not int or record['schemaVersion'] != 1:
            raise ValueError('Unsupported saved answer version')
        value['limitations'] = tuple(value['limitations'])
        if value.get('chart') is not None: value['chart'] = ResultChart.from_dict(value['chart'])
        return cls(**value)

    @classmethod
    def from_json(cls, raw: str) -> 'AnswerResult':
        if not isinstance(raw, str) or len(raw.encode('utf-8')) > 2 * 1024 * 1024:
            raise ValueError('Invalid answer envelope size')
        def unique(pairs):
            value = {}
            for key, item in pairs:
                if key in value: raise ValueError('Duplicate answer field')
                value[key] = item
            return value
        value = json.loads(raw, object_pairs_hook=unique)
        fields = {'schemaVersion', 'title', 'full_text', 'spoken_summary', 'kind', 'visual', 'limitations'}
        if not isinstance(value, dict) or set(value) not in (fields, fields | {'chart'}) or type(value['schemaVersion']) is not int or value['schemaVersion'] != 1:
            raise ValueError('Unsupported answer envelope')
        if not isinstance(value['limitations'], list): raise ValueError('Invalid limitations')
        return cls(value['full_text'], value['spoken_summary'], value['title'], value['kind'],
                   value['visual'], tuple(value['limitations']), chart=ResultChart.from_dict(value['chart']) if value.get('chart') is not None else None)

    @classmethod
    def from_legacy(cls, text: str, *, format_issue: str | None = None) -> 'AnswerResult':
        # A compatibility failure must never throw away a valid complete answer,
        # nor turn its raw JSON or a truncated first sentence into a fake summary.
        if isinstance(text, str):
            try:
                value = json.loads(text)
                if isinstance(value, dict) and isinstance(value.get('full_text'), str) and value['full_text'].strip():
                    text = value['full_text']
            except (ValueError, TypeError): pass
        return cls(text, '', kind='partial' if format_issue else 'answer', format_issue=format_issue)

    @property
    def display_text(self) -> str:
        text = self.full_text
        if self.chart:
            def cell(value): return str(value).replace('|', '\\|')
            header = [self.chart.xTitle, *self.chart.series, '來源／備註']
            rows = [[x, *['—' if v is None else str(v) for v in values], note] for x, values, note in self.chart.rows]
            text += '\n\n### 圖表資料\n\n' + self.chart.caption + '\n\n'
            text += '| ' + ' | '.join(map(cell, header)) + ' |\n| ' + ' | '.join(['---'] * len(header)) + ' |\n'
            text += '\n'.join('| ' + ' | '.join(map(cell, row)) + ' |' for row in rows)
        if self.limitations: text += '\n\n資料與結果限制：\n' + '\n'.join('• ' + item for item in self.limitations)
        return text

    @property
    def needs_document(self) -> bool:
        if self.chart is not None: return True
        if self.visual == 'none': return False
        return self.visual == 'document' or len(self.display_text) > 240 or any(
            marker in self.full_text for marker in ('http://', 'https://', '```', '\n|'))


@dataclass(frozen=True)
class SpeechPolicy:
    target_seconds: float = 15
    words_per_minute: float = 175

    def estimated_seconds(self, text: str) -> float:
        cjk = len(re.findall(r'[\u3400-\u9fff]', text))
        words = len(re.findall(r'[A-Za-z0-9]+', text))
        return cjk / 4 + words * 60 / max(1, self.words_per_minute)

    def choose(self, result: AnswerResult, *, source: str | None, mode: str = 'auto') -> str:
        if mode not in {'auto', 'summary', 'mute', 'read'}: raise ValueError('Invalid speech mode')
        if mode == 'mute' or (mode == 'auto' and source in {'native', 'web'}): return ''
        if mode == 'read':
            cue = {'partial': '任務仍有待核對事項。以下朗讀原始結果，核對細節請見聊天。',
                   'needs_input': '目前仍需要你的確認。以下朗讀原始結果，確認事項請見聊天。',
                   'failed': '這次處理未成功。以下朗讀原始結果與限制。'}.get(result.kind, '')
            return cue + result.display_text
        text = self.summary_candidate(result)
        if not self.summary_is_usable(result):
            if result.kind == 'failed': return '這次處理未成功，請查看文字中的原因與限制。'
            if result.kind == 'needs_input': return '需要你補充或確認，請查看文字中的問題。'
            return '語音摘要暫時無法可靠精簡，請查看完整文字與限制。'
        return text.strip()

    def summary_candidate(self, result: AnswerResult) -> str:
        text = result.spoken_summary
        if not text and not result.needs_document and not result.format_issue:
            text = result.full_text
        # A status cue alone is not a summary of the actual result. In
        # particular, an empty worker summary must reach the repair path.
        if not text.strip(): return ''
        if result.kind == 'failed': text = '這次處理未成功。' + text
        # Data qualifications and partial work are not requests for human approval.
        # Their concrete meaning belongs in the model's summary and full answer.
        return text

    def summary_is_usable(self, result: AnswerResult) -> bool:
        text = self.summary_candidate(result)
        unsuitable = re.search(r'https?://|www\.|```|(?:^|\s)(?:/[^\s]+|[A-Za-z]:\\)', text)
        return bool(text.strip()) and not unsuitable and self.estimated_seconds(text) <= self.target_seconds


@dataclass(frozen=True)
class SpeechControl:
    mode: str | None = None
    request: str | None = None
    read_previous: bool = False

    @classmethod
    def parse(cls, text: str) -> 'SpeechControl':
        # Interpret only a complete human command or an explicit leading control
        # followed by a delimiter. Quoted/narrative occurrences remain content.
        match = re.fullmatch(r'\s*(念給我聽|念给我听|讀給我聽|读给我听|朗讀上一則|朗读上一则|先別說話|先别说话|先不要說話|先不要说话)(?:[，,:：]\s*(.+))?[。.!！\s]*', text, re.DOTALL)
        if match:
            read = match[1].startswith(('念', '讀', '读', '朗'))
            request = match[2].strip() if match[2] else None
            return cls('read' if read else 'mute', request, read and request is None)
        if re.fullmatch(r'\s*(詳細說|详细说|詳細說明|详细说明)[。.!！\s]*', text):
            return cls('read', text)
        return cls(request=text)


def with_assessment(result: AnswerResult, assessment: dict) -> AnswerResult:
    """Reflect accepted review without replacing the finding with a status slogan."""
    from dataclasses import replace
    status = assessment.get('status')
    if status not in {'partial', 'needs_input', 'unavailable'}: return result
    remaining = [item.strip() for item in assessment.get('remaining', []) if isinstance(item, str) and item.strip()]
    reason = remaining[0] if remaining else assessment.get('summary', '').strip()
    if not reason: reason = '自動核對沒有回傳具體原因；完整回答已保留。'
    base = result.spoken_summary.strip()
    # A host review can reject the model's success claim while retaining findings.
    base = re.sub(r'全部(?:完成|測試通過|测试通过)|所有測試(?:均已|都)?通過|all (?:done|complete|tests passed)', '', base, flags=re.IGNORECASE).strip(' 。.!！')
    summary = base if reason in base else (base + ' ' if base else '') + ('需要你決定：' if status == 'needs_input' else '尚未核實：') + reason
    return replace(result, spoken_summary=summary, kind='needs_input' if status == 'needs_input' else 'partial')
