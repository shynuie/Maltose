"""Start the configured real brain in text-only mode; send no model prompt."""
from __future__ import annotations
import argparse
import json
import os
from pathlib import Path
import queue
import signal
import subprocess
import sys
import threading
import time


def smoke(directory: Path, module_root: Path, log: Path, *, deny_legacy_root: Path | None = None):
    environment = {**os.environ, 'PYTHONPATH': str(module_root), 'PYTHONDONTWRITEBYTECODE': '1',
        'HF_HUB_OFFLINE': '1', 'TRANSFORMERS_OFFLINE': '1'}
    messages = queue.Queue()
    command = [str(directory / 'environments/main/bin/python'), '-m', 'maltose.desktop',
        '--config', str(directory / 'maltose.toml'), '--native-text-only']
    if deny_legacy_root is not None:
        policy = '(version 1)(allow default)(deny file-read* (subpath ' + json.dumps(str(deny_legacy_root)) + '))'
        probe = deny_legacy_root / 'myagent.toml'
        if not probe.is_file(): raise RuntimeError('Legacy deny probe needs an existing configuration')
        blocked = subprocess.run(['/usr/bin/sandbox-exec', '-p', policy, '/bin/cat', str(probe)], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        if blocked.returncode == 0: raise RuntimeError('Legacy source read restriction was ineffective')
        command = ['/usr/bin/sandbox-exec', '-p', policy, *command]
    with log.open('w') as diagnostics:
        process = subprocess.Popen(command,
            cwd=directory, env=environment, stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=diagnostics, text=True)
        def collect():
            for line in process.stdout:
                try: messages.put(json.loads(line))
                except ValueError: messages.put({'invalidProtocol': True})
        thread = threading.Thread(target=collect, daemon=True); thread.start()
        group = None
        def send(identifier, method):
            process.stdin.write(json.dumps({'schemaVersion': 1, 'requestID': identifier, 'method': method}) + '\n'); process.stdin.flush()
        def until(predicate, timeout=180):
            deadline = time.monotonic() + timeout
            while time.monotonic() < deadline:
                try: message = messages.get(timeout=.5)
                except queue.Empty:
                    if process.poll() is not None: raise RuntimeError(f'Managed runtime exited with {process.returncode}; inspect private diagnostics')
                    continue
                if message.get('invalidProtocol'): raise RuntimeError('Non-protocol output was written to stdout')
                if predicate(message): return message
            raise TimeoutError('Managed runtime did not reach the requested state')
        try:
            send('initialize', 'initialize')
            initialized = until(lambda message: message.get('requestID') == 'initialize')
            if not initialized.get('ok'): raise RuntimeError('Initialization handshake failed')
            if initialized['result']['pid'] != process.pid or initialized['result']['processGroupID'] != process.pid:
                raise RuntimeError('Managed process identity mismatch')
            group = process.pid
            until(lambda message: message.get('notification') == 'ready')
            send('snapshot', 'snapshot')
            snapshot = until(lambda message: message.get('requestID') == 'snapshot')
            if not snapshot.get('ok') or not snapshot['result']['ready']: raise RuntimeError('Runtime was not actually ready')
            send('shutdown', 'shutdown'); process.stdin.close()
            if process.wait(timeout=20) != 0: raise RuntimeError('Managed runtime did not exit cleanly')
            return {'handshake': 'passed', 'configuredBrainReady': True, 'shutdown': 'passed',
                'modelPromptSent': False, 'microphoneUsed': False, 'legacyRootReadDenied': deny_legacy_root is not None}
        finally:
            if process.poll() is None:
                if group: os.killpg(group, signal.SIGTERM)
                else: process.terminate()
                try: process.wait(timeout=5)
                except subprocess.TimeoutExpired:
                    if group: os.killpg(group, signal.SIGKILL)
                    else: process.kill()
                    process.wait(timeout=5)
            if not process.stdin.closed: process.stdin.close()
            process.stdout.close()


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('directory', type=Path)
    parser.add_argument('--modules', type=Path, required=True)
    parser.add_argument('--log', type=Path, required=True)
    parser.add_argument('--deny-legacy-root', type=Path)
    args = parser.parse_args()
    print(json.dumps(smoke(args.directory.resolve(), args.modules.resolve(), args.log, deny_legacy_root=args.deny_legacy_root)))
