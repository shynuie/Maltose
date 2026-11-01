"""Private native owner lifetime and durable daemon-resource cleanup."""
from __future__ import annotations
import argparse
import atexit
import json
import logging
import os
from pathlib import Path
import select
import shutil
import signal
import socket
import subprocess
import sys
import threading
import time
import uuid

from maltose.runtime.processes import Descendants, Identity
from maltose.runtime.resources import DockerResources

logger = logging.getLogger(__name__)
_current = None


def current_lifetime():
    return _current


class NativeRuntimeLifetime:
    maximum_frame = 4 * 1024 * 1024

    def __init__(self, directory: Path, *, lease_fd: int):
        global _current
        self._close_lock = threading.Lock(); self._rpc_lock = threading.Lock()
        self._socket = None; self._buffer = bytearray()
        self.process = None; self.failed = False; self.finishing = False; self._control = None
        self.resources = DockerResources(directory / 'native-executions', shutil.which('docker'), uuid.uuid4().hex)
        root, host = Identity.read(os.getpid()), Identity.read(os.getppid())
        if host.pid <= 1 or os.getpgrp() != root.pid:
            raise RuntimeError('Native runtime requires an isolated process group and a live owner')
        parent, child = socket.socketpair(); ready_read, ready_write = os.pipe()
        try:
            self._socket = parent
            arguments = [sys.executable, '-m', 'maltose.runtime.lifetime',
                '--root-pid', str(root.pid), '--root-created', str(root.created),
                '--host-pid', str(host.pid), '--host-created', str(host.created),
                '--control-fd', str(child.fileno()), '--ready-fd', str(ready_write),
                '--lease-fd', str(lease_fd), '--resources', str(self.resources.directory),
                '--scope', self.resources.scope]
            if self.resources.binary: arguments += ['--docker-binary', self.resources.binary]
            self.process = subprocess.Popen(arguments, stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL,
                stderr=sys.stderr, pass_fds=(child.fileno(), ready_write, lease_fd), start_new_session=True)
            child.close(); os.close(ready_write); ready_write = None
            # Recovery may require bounded daemon operations before any model starts.
            if not select.select([ready_read], [], [], 20)[0] or os.read(ready_read, 1) != b'1':
                raise RuntimeError('Native lifetime guard or pending Docker cleanup did not initialize; inspect runtime diagnostics')
        except BaseException:
            self.owner_disconnected()
            if self.process is not None:
                self.process.terminate()
                try: self.process.wait(timeout=2)
                except subprocess.TimeoutExpired:
                    self.process.kill(); self.process.wait(timeout=2)
            raise
        finally:
            child.close(); os.close(ready_read)
            if ready_write is not None: os.close(ready_write)
        _current = self
        atexit.register(self.finish)
        def watch_guard():
            self.process.wait()
            if self.finishing: return
            self.failed = True
            if self._control is not None: self._control.close()
            logger.error('native_lifetime_guard_ended_before_runtime')
            # IDs were saved before start, so even guard loss cannot strand a
            # known running container. Unconfirmed creation remains on disk.
            try: self.resources.recover()
            except Exception: logger.exception('native_lifetime_emergency_resource_cleanup_failed')
            os.kill(root.pid, signal.SIGTERM)
            time.sleep(2)
            if os.getpgrp() == root.pid: os.killpg(root.pid, signal.SIGKILL)
            else: os.kill(root.pid, signal.SIGKILL)
        threading.Thread(target=watch_guard, name='maltose-runtime-guard-monitor', daemon=True).start()

    def attach_control(self, control):
        self._control = control
        if self.failed: control.close()

    def fail_closed(self, reason):
        self.failed = True
        if self._control is not None: self._control.close()
        logger.error('native_resource_cleanup_unconfirmed reason=%s', reason)
        self.owner_disconnected()
        os.kill(os.getpid(), signal.SIGTERM)
        raise RuntimeError(reason)

    def _request(self, method, **params):
        with self._rpc_lock:
            connection = self._socket
            if connection is None or self.failed: raise RuntimeError('Native resource guardian is unavailable')
            request = dict(requestID=uuid.uuid4().hex, method=method, **params)
            frame = json.dumps(request, allow_nan=False).encode() + b'\n'
            if len(frame) > self.maximum_frame: raise ValueError('Native resource request exceeds size limit')
            connection.settimeout(25)
            connection.sendall(frame)
            while b'\n' not in self._buffer:
                chunk = connection.recv(65536)
                if not chunk: raise RuntimeError('Native resource guardian disconnected; outcome must not be replayed')
                self._buffer.extend(chunk)
                if len(self._buffer) > self.maximum_frame: raise RuntimeError('Invalid native resource response')
            line, _, rest = self._buffer.partition(b'\n'); self._buffer = bytearray(rest)
            response = json.loads(line)
            if response.get('requestID') != request['requestID']: raise RuntimeError('Native resource response identity mismatch')
            if not response.get('ok'):
                if response.get('unsafe'): self.fail_closed(response.get('error', 'Native resource cleanup unconfirmed'))
                raise RuntimeError(response.get('error', 'Native resource operation failed'))
            return response

    def create_docker(self, execution, command):
        return self._request('create', executionID=execution, command=command)['containerID']

    def cleanup_docker(self, execution):
        try: self._request('cleanup', executionID=execution)
        except Exception as error: self.fail_closed(str(error))

    def owner_disconnected(self):
        # Closing must wake a model waiting on create; never wait for its RPC lock.
        with self._close_lock:
            connection, self._socket = self._socket, None
            if connection is not None:
                try: connection.shutdown(socket.SHUT_RDWR)
                except OSError: pass
                connection.close()

    def finish(self):
        if self._socket is None: return  # Abrupt owner loss: independent guard owns cleanup.
        self.finishing = True
        try:
            self._request('finish')
            if self.process.wait(timeout=5) != 0: raise RuntimeError('Native guardian did not confirm cleanup')
        except BaseException:
            logger.exception('native_lifetime_final_cleanup_unconfirmed')
            self.owner_disconnected()
            os._exit(70)  # atexit exceptions alone would incorrectly return success.
        self.owner_disconnected()


def guard(root, host, connection, ready_fd, resources):
    tracker = Descendants(root); buffer = bytearray()
    try:
        if root.process() is None or host.process() is None:
            raise RuntimeError('Native owner ended during lifetime setup')
        resources.recover()  # Remove only; never replay an interrupted create/start.
        tracker.collect(); os.write(ready_fd, b'1'); os.close(ready_fd); ready_fd = None
        while root.process() is not None and host.process() is not None:
            tracker.collect()
            if not select.select([connection], [], [], .05)[0]: continue
            data = connection.recv(65536)
            if not data: break
            buffer.extend(data)
            if len(buffer) > NativeRuntimeLifetime.maximum_frame: raise RuntimeError('Native resource frame exceeds size limit')
            if b'\n' not in buffer: continue
            line, _, remaining = buffer.partition(b'\n'); buffer = bytearray(remaining)
            request = json.loads(line); identifier = request.get('requestID')
            if not isinstance(identifier, str) or len(identifier) != 32: raise ValueError('Invalid resource request identity')
            finish = False
            try:
                if request.get('method') == 'create':
                    container = resources.create(request.get('executionID'), request.get('command'))
                    response = dict(containerID=container)
                elif request.get('method') == 'cleanup':
                    resources.cleanup(request.get('executionID'), current_scope=True); response = {}
                elif request.get('method') == 'finish':
                    resources.recover()
                    if not tracker.stop(timeout=3, grace=1, include_root=False): raise RuntimeError('Native descendants remain active')
                    response = {}; finish = True
                else: raise ValueError('Unknown native resource operation')
                # Creation can finish after the App has vanished. No start ACK
                # is sent to an ended owner; the durable container is removed.
                if root.process() is None or host.process() is None: break
                connection.sendall(json.dumps(dict(requestID=identifier, ok=True, **response)).encode()+b'\n')
                if finish: return 0
            except (BrokenPipeError, ConnectionError): break
            except Exception as error:
                connection.sendall(json.dumps(dict(requestID=identifier, ok=False, error=str(error), unsafe=resources.has_pending())).encode()+b'\n')
        # Let cooperative database/audio shutdown finish before forced cleanup.
        deadline = time.monotonic() + 2
        while root.process() is not None and time.monotonic() < deadline:
            tracker.collect(); time.sleep(.05)
        if not tracker.stop(timeout=3, grace=1): raise RuntimeError('Native descendant cleanup was not confirmed')
        resources.recover()
        return 0
    except Exception:
        logger.exception('native_lifetime_cleanup_failed')
        try: tracker.stop(timeout=3, grace=1)
        except Exception: logger.exception('native_lifetime_process_cleanup_retry_failed')
        try: resources.recover()
        except Exception: logger.exception('native_lifetime_resource_cleanup_retry_failed')
        return 2
    finally:
        connection.close()
        if ready_fd is not None: os.close(ready_fd)


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--root-pid', type=int, required=True); parser.add_argument('--root-created', type=float, required=True)
    parser.add_argument('--host-pid', type=int, required=True); parser.add_argument('--host-created', type=float, required=True)
    parser.add_argument('--control-fd', type=int, required=True); parser.add_argument('--ready-fd', type=int, required=True)
    parser.add_argument('--lease-fd', type=int, required=True); parser.add_argument('--resources', type=Path, required=True)
    parser.add_argument('--scope', required=True); parser.add_argument('--docker-binary')
    args = parser.parse_args()
    try:
        result = guard(Identity(args.root_pid, args.root_created), Identity(args.host_pid, args.host_created),
            socket.socket(fileno=args.control_fd), args.ready_fd, DockerResources(args.resources, args.docker_binary, args.scope))
    finally: os.close(args.lease_fd)  # Same kernel lease persists through daemon cleanup.
    raise SystemExit(result)
