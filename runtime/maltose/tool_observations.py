"""Bounded, immutable tool returns scoped to one actual worker invocation.

Context variables do not inherit a Main identity or another executor thread's
receipts. Worker return strings cannot supply these observations.
"""
from contextlib import contextmanager
from contextvars import ContextVar
import hashlib
import json
import uuid

_collector = ContextVar('maltose_worker_tool_observations', default=None)
_allowed = {'read_web_page','read_file', 'create_file', 'write_file', 'replace_file_text', 'copy_file', 'execute_command', 'get_current_datetime', 'search_web', 'web_search'}


def normalize_tool_return(name, result):
    # The foreground registry returns a list; the research worker already returns
    # this wrapper. Both represent search snippets, never fetched page contents.
    if name == 'web_search' and isinstance(result, list):
        return dict(sources=result, granularity='search_results', complete=True)
    return result


@contextmanager
def collect_tool_returns():
    items = []
    token = _collector.set(items)
    try: yield items
    finally: _collector.reset(token)


def observe_tool_return(name, arguments, result):
    items = _collector.get()
    if items is None or (name not in _allowed and not (name.startswith('maltose_') and name not in {'maltose_get_user_view', 'maltose_list_capabilities'})): return
    if len(items) >= 64:
        if items[-1]['tool'] != 'workflow_observation_limit':
            items[-1] = dict(id=uuid.uuid4().hex, tool='workflow_observation_limit', arguments={},
                result={'note': 'The complete worker observation budget was exceeded.'}, truncated=True)
        return
    result = normalize_tool_return(name, result)
    identity = uuid.uuid4().hex
    try:
        raw = json.dumps(dict(arguments=arguments, result=result), ensure_ascii=False, allow_nan=False)
        if len(raw.encode()) > 24000:
            items.append(dict(id=identity, tool=name, arguments={}, result=dict(sha256=hashlib.sha256(raw.encode()).hexdigest(),
                note='Full worker tool return exceeded the evidence budget.'), truncated=True))
        else:
            items.append(dict(id=identity, tool=name, **json.loads(raw), truncated=False))
    except (TypeError, ValueError, UnicodeError):
        items.append(dict(id=identity, tool=name, arguments={}, result={'note': 'Worker tool return could not be preserved completely.'}, truncated=True))
