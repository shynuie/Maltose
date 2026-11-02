"""Give the app-owned Codex harness an isolated group and a private lifetime guardian."""
import json
import os
from pathlib import Path
import select
import subprocess
import sys


def main():
    guardian=None
    read_fd=write_fd=None
    try:
        if os.getpgrp()!=os.getpid(): os.setsid()
        if len(sys.argv)<2 or not Path(sys.argv[1]).is_absolute() or not os.access(sys.argv[1],os.X_OK):
            raise ValueError('An installed absolute Codex executable is required')
        from maltose.codex.lifetime import Identity
        root=Identity.read(os.getpid()); host=Identity.read(os.getppid())
        if host.pid<=1: raise RuntimeError('Native owner ended before Codex startup')
        read_fd,write_fd=os.pipe()
        # Holding stdout keeps the native EOF lease until descendant cleanup.
        # This separate group never reads user RPC or starts model work.
        guardian=subprocess.Popen([sys.executable,'-m','maltose.codex.lifetime',
            '--root-pid',str(root.pid),'--root-created',str(root.created),
            '--host-pid',str(host.pid),'--host-created',str(host.created),'--ready-fd',str(write_fd)],
            stdin=subprocess.DEVNULL,stdout=sys.stdout,stderr=sys.stderr,pass_fds=(write_fd,),start_new_session=True)
        os.close(write_fd); write_fd=None
        ready=select.select([read_fd],[],[],5)[0]
        if not ready or os.read(read_fd,1)!=b'1': raise RuntimeError('Codex lifetime protection could not start')
        os.close(read_fd); read_fd=None
        os.execv(sys.argv[1],sys.argv[1:])
    except BaseException:
        if guardian is not None and guardian.poll() is None:
            guardian.terminate()
            try: guardian.wait(timeout=2)
            except subprocess.TimeoutExpired: guardian.kill(); guardian.wait(timeout=2)
        # exec never returned: Codex was never launched. This startup-only
        # receipt permits retry after repairing an unavailable dependency.
        data=dict(method='maltose/lifetime/startup_aborted',params=dict(rootPID=os.getpid()))
        try: os.write(1,(json.dumps(data)+'\n').encode())
        except BrokenPipeError: pass
        raise
    finally:
        for descriptor in (read_fd,write_fd):
            if descriptor is not None: os.close(descriptor)


if __name__=='__main__': main()
