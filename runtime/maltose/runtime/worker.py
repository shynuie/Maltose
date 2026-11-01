"""Run an existing worker module with native-runtime parent lifetime tracking."""
from __future__ import annotations
import os
import runpy
import signal
import sys
import threading


def main():
    if len(sys.argv)>2 and sys.argv[1]=='--exec-after-ready':
        # Parent must durably register this PID before allowing a daemon request.
        # If it dies before admission, EOF exits without executing anything.
        if sys.stdin.buffer.read(1)!=b'1': return
        if not os.path.isabs(sys.argv[2]): raise ValueError('Worker executable must be absolute')
        os.execv(sys.argv[2],sys.argv[2:])
    module = sys.argv[1]
    sys.argv = [module, *sys.argv[2:]]

    def interrupted(_signal, _frame): raise KeyboardInterrupt
    signal.signal(signal.SIGTERM, interrupted)

    def parent_closed():
        # The pipe carries no user input; its lifetime is the parent's lease.
        while sys.stdin.buffer.read(1): pass
        os.kill(os.getpid(), signal.SIGINT)

    threading.Thread(target=parent_closed, daemon=True, name='maltose-worker-parent').start()
    try: runpy.run_module(module, run_name='__main__')
    except KeyboardInterrupt: pass


if __name__ == '__main__': main()
