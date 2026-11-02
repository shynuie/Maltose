"""Controller-only local services; never registered as unrestricted model tools."""
from __future__ import annotations
import json
import hashlib
import os
import stat
import threading
from pathlib import Path

from maltose.codex.workspaces import CodexWorkspaceManager

CONTROL_OWNER = 'maltose-codex-coordinator'


class NativeCollaborationService:
    def __init__(self, directory: Path, repository: Path):
        self.directory = Path(directory).resolve() / 'collaboration'
        self.repository = Path(repository).expanduser().resolve()
        if self.directory.is_symlink(): raise PermissionError('Collaboration directory cannot be a symbolic link')
        self._lock = threading.RLock()
        self._review_lock = threading.Lock()
        self._inputs_path = self.directory / 'pending-inputs.json'
        self._inputs = self._load(self._inputs_path, {'schemaVersion': 1, 'inputs': {}})
        if self._inputs.get('schemaVersion') != 1 or not isinstance(self._inputs.get('inputs'), dict):
            raise ValueError('Invalid collaboration input journal')
        self.last_observation = self._load(self.directory / 'observation.json', None)
        repositories = self._load(self.directory / 'repositories.json', None)
        self.authorized_repositories = {self.repository}
        if repositories is not None:
            if not isinstance(repositories, dict) or repositories.get('schemaVersion') != 1 or not isinstance(repositories.get('authorized'), list):
                raise ValueError('Invalid development repository settings')
            paths = repositories['authorized']
            if not all(isinstance(path, str) and Path(path).is_absolute() for path in paths) or repositories.get('selected') not in paths:
                raise ValueError('Invalid development repository authorization')
            self.authorized_repositories = {Path(path) for path in paths}
            self.repository = Path(repositories['selected'])

    @staticmethod
    def _load(path, default):
        try: fd = os.open(path, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK)
        except FileNotFoundError: return default
        with os.fdopen(fd, 'rb') as stream:
            info = os.fstat(stream.fileno())
            if not stat.S_ISREG(info.st_mode) or info.st_uid != os.getuid() or info.st_mode & 0o077 or info.st_nlink != 1:
                raise PermissionError('Collaboration state must be an owner-only regular file')
            if info.st_size > 16 * 1024 * 1024: raise ValueError('Collaboration state exceeds size limit')
            return json.loads(stream.read(16 * 1024 * 1024 + 1))

    def _ensure_directory(self):
        if self.directory.is_symlink(): raise PermissionError('Collaboration directory cannot be a symbolic link')
        self.directory.mkdir(parents=True, exist_ok=True, mode=0o700)

    def pending_inputs(self):
        with self._lock: return list(self._inputs['inputs'].values())

    def save_input(self, payload):
        identity = payload['messageID']
        if not isinstance(identity, str) or not identity or len(identity) > 128: raise ValueError('Invalid collaboration input ID')
        with self._lock:
            previous = self._inputs['inputs'].get(identity)
            if previous is not None:
                if previous != payload: raise ValueError('Collaboration input ID conflicts with its saved content')
                return
            if len(self._inputs['inputs']) >= 1024: raise RuntimeError('Collaboration input outbox is full')
            self._ensure_directory()
            next_state = {'schemaVersion': 1, 'inputs': {**self._inputs['inputs'], identity: payload}}
            if len(json.dumps(next_state).encode()) > 16 * 1024 * 1024:
                raise RuntimeError('Collaboration input outbox exceeds size limit')
            CodexWorkspaceManager._save(self._inputs_path, next_state)
            self._inputs = next_state

    def acknowledge(self, identity):
        if not isinstance(identity, str): raise ValueError('Invalid collaboration input ID')
        with self._lock:
            if identity not in self._inputs['inputs']: return
            next_state = {'schemaVersion': 1, 'inputs': {key: value for key, value in self._inputs['inputs'].items() if key != identity}}
            CodexWorkspaceManager._save(self._inputs_path, next_state); self._inputs = next_state

    def info(self):
        return {'repository': str(self.repository), 'available': (self.repository / '.git').exists()}

    def select_repository(self, path):
        if not isinstance(path, str) or not Path(path).is_absolute(): raise ValueError('An absolute Git repository path is required')
        repository = Path(path).resolve(strict=True)
        if not repository.is_dir(): raise ValueError('A Git repository directory is required')
        top = Path(os.fsdecode(CodexWorkspaceManager._git(repository, 'rev-parse', '--show-toplevel')).strip()).resolve()
        if top != repository: raise ValueError('Select the exact Git repository root')
        CodexWorkspaceManager._git(repository, 'rev-parse', 'HEAD')
        with self._lock:
            self._ensure_directory()
            authorized = self.authorized_repositories | {repository}
            CodexWorkspaceManager._save(self.directory / 'repositories.json', dict(schemaVersion=1,
                selected=str(repository), authorized=sorted(map(str, authorized))))
            self.authorized_repositories = authorized; self.repository = repository
            return self.info()

    def workspace(self, operation, task_id):
        self._ensure_directory()
        manager = CodexWorkspaceManager(self.directory / 'workspaces', authorized_repositories=tuple(
            path for path in self.authorized_repositories if path.exists()))
        if operation == 'prepare': return manager.prepare(self.repository, task_id)
        if operation == 'inspect': return manager.inspect(task_id)
        if operation == 'changes': return manager.changes(task_id)
        raise ValueError('Unsupported workspace operation')

    def observe(self, record):
        if not isinstance(record, dict) or not all(isinstance(record.get(key), str) and record[key] for key in ('taskID', 'conversationID', 'threadID')):
            raise ValueError('Collaboration observation lacks identity')
        if len(json.dumps(record).encode()) > 512 * 1024: raise ValueError('Collaboration observation exceeds limit')
        with self._lock:
            record = {key: value for key, value in record.items() if key != 'mainReview'}
            previous = self.last_observation
            if isinstance(previous, dict) and all(previous.get(key) == record.get(key) for key in ('taskID', 'threadID', 'lastFinishedTurnID')) and record.get('status') in ('awaitingReview', 'completed'):
                if 'mainReview' in previous:
                    review = {**previous['mainReview']}
                    if record.get('deliveredReviewID') == review.get('messageID'): review['delivery'] = 'accepted'
                    record = {**record, 'mainReview': review}
            self._ensure_directory()
            CodexWorkspaceManager._save(self.directory / 'observation.json', record)
            self.last_observation = record
            return record

    def attach_review(self, observed, question, result):
        with self._lock:
            if self.last_observation != observed: raise RuntimeError('Collaboration changed during review; refresh before asking')
            previous = observed.get('mainReview', {})
            delivery = 'accepted' if previous.get('messageID') == question['messageID'] and previous.get('delivery') == 'accepted' else 'generated'
            enriched = {**observed, 'mainReview': {'messageID': question['messageID'], 'source': 'maltose-review',
                'mode': result['mode'], 'content': result['content'], 'review': result.get('review'), 'delivery': delivery}}
            CodexWorkspaceManager._save(self.directory / 'observation.json', enriched)
            self.last_observation = enriched
            return enriched

    def review(self, record, question, generate, *, namespace='reviews'):
        if namespace not in {'reviews', 'product-assessments'}: raise ValueError('Invalid review namespace')
        identity = question['messageID']
        # Delivery acknowledgement changes after projection; it is transport
        # metadata, not a different request to the read-only model.
        context = {key: value for key, value in record.items() if key != 'deliveredReviewID'}
        fingerprint = hashlib.sha256(json.dumps({'record': context, 'question': question},
            sort_keys=True, ensure_ascii=False).encode()).hexdigest()
        path = self.directory / namespace / (hashlib.sha256(identity.encode()).hexdigest() + '.json')
        # Separate from the input/outbox lock: a model call must not block voice capture.
        with self._review_lock:
            if path.parent.is_symlink(): raise PermissionError('Review directory cannot be a symbolic link')
            saved = self._load(path, None)
            if saved is not None:
                if saved.get('schemaVersion') != 1 or saved.get('fingerprint') != fingerprint:
                    raise ValueError('Review message ID conflicts with its saved collaboration context')
                if saved.get('status') == 'complete': return saved['result']
            self._ensure_directory(); path.parent.mkdir(mode=0o700, exist_ok=True)
            if path.parent.is_symlink(): raise PermissionError('Review directory cannot be a symbolic link')
            state = dict(schemaVersion=1, fingerprint=fingerprint, messageID=identity, status='started')
            CodexWorkspaceManager._save(path, state)
            # After a crash a read-only model call may be recomputed. It has no tools
            # or autonomous actions, and only the saved result is ever published.
            result = generate()
            if not isinstance(result, dict) or result.get('mode') not in ('model', 'template') or not isinstance(result.get('content'), str):
                raise ValueError('Invalid collaboration review result')
            if not result['content'].strip() or len(result['content'].encode()) > 256 * 1024:
                raise ValueError('Collaboration review result exceeds the content limit')
            CodexWorkspaceManager._save(path, {**state, 'status': 'complete', 'result': result})
            return result
