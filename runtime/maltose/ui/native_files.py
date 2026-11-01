"""Native panel file I/O runs through the existing filesystem boundary.

The app only receives validated bytes or exports a document snapshot. It never
opens an LLM-supplied path on behalf of the native Agent transport.
"""
from __future__ import annotations
import base64
from pathlib import Path


class NativePanelFileAdapter:
    maximum_file_bytes = 2 * 1024 * 1024

    def __init__(self, bridge): self.bridge = bridge

    def _resolve(self, raw_path: str, *, must_exist: bool):
        service = self.bridge.file_service
        if service is None:
            raise PermissionError('Filesystem capabilities are not enabled for this Agent')
        candidate = Path(raw_path).expanduser()
        if not candidate.is_absolute():
            raise PermissionError('A native file path must be absolute and inside a configured root')
        matches = []
        for root in service.resolver.configured_roots():
            try: relative = candidate.relative_to(root.path)
            except ValueError: continue
            matches.append((len(root.path.parts), root, relative))
        if not matches:
            raise PermissionError('Native file path is outside configured filesystem roots')
        _, root, relative = max(matches, key=lambda item: item[0])
        resolved = service.resolver.resolve(root.name, relative, must_exist=must_exist)
        return service, root.name, resolved

    def call(self, command: str, arguments: dict) -> dict:
        arguments = dict(arguments)
        expected = arguments.pop('expectedSHA256', None)
        if command != 'flowchart_save':
            service, root, resolved = self._resolve(arguments['path'], must_exist=True)
            arguments['path'] = str(resolved.path)
            result = service.read_bytes(root, resolved.relative_path,
                max_bytes=min(service.policy.max_read_bytes, self.maximum_file_bytes))
            response = self.bridge.call_panel({command: arguments}, file_transfer={
                'mode': 'load', 'data': base64.b64encode(result['data']).decode('ascii')})
            return response
        service, root, resolved = self._resolve(arguments['path'], must_exist=False)
        arguments['path'] = str(resolved.path)
        # Authorize before exporting UI data; FileService rechecks with size and CAS at write.
        service.policy.require_allowed(root, 'write', target=resolved)
        exported = self.bridge.call_panel({command: arguments}, file_transfer={'mode': 'export'})
        if not exported.get('ok'): return exported
        result = exported['result']
        data = base64.b64decode(result['data'], validate=True)
        if len(data) > self.maximum_file_bytes:
            raise ValueError('Native panel file exceeds the transfer limit')
        expected = expected if expected is not None else result.get('knownFileSHA256')
        written = service.write_bytes(root, resolved.relative_path, data, expected_sha256=expected)
        try:
            acknowledged = self.bridge.call_panel({command: arguments}, file_transfer={
                'mode': 'saved', 'documentID': result['documentID'], 'fingerprint': result['fingerprint'],
                'fileSHA256': written['sha256']})
        except (ConnectionError, TimeoutError) as error:
            acknowledged = {'ok': False, 'error': {'code': 'acknowledgement_unavailable', 'message': str(error)}}
        # A successful filesystem write remains a success if the user changed panels meanwhile.
        # Report acknowledgement separately instead of claiming the current document is clean.
        return {'ok': True, 'result': {**written, 'panelAcknowledgement': acknowledged}}
