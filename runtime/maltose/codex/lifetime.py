"""Private guardian for observed Codex descendants, outside the server process group."""
from __future__ import annotations
import argparse
import json
import os
import signal
import sys
import time
import uuid



from maltose.runtime.processes import Descendants, Identity


def notify(method, root, token, **values):
    data=('\n' if method!='started' else '')+json.dumps(dict(method='maltose/lifetime/'+method,params=dict(rootPID=root.pid,token=token,**values)))+'\n'
    try: os.write(1,data.encode())
    except BrokenPipeError: pass  # The UI itself may have crashed.


def guard(root, host, ready_fd):
    tracker=Descendants(root); token=str(uuid.uuid4())
    try:
        if root.process() is None or host.process() is None: raise RuntimeError('Native owner ended during startup')
        tracker.collect()
        notify('started',root,token,guardianPID=os.getpid())
        os.write(ready_fd,b'1'); os.close(ready_fd); ready_fd=None
        while root.process() is not None and host.process() is not None:
            tracker.collect(); time.sleep(.05)
        if not tracker.stop(): raise RuntimeError('Owned descendant cleanup could not be confirmed')
        notify('cleaned',root,token)
        return 0
    except Exception:
        try: tracker.stop()
        except Exception: pass
        notify('failed',root,token,message='Codex 背景程序清理尚未確認；麥芽糖保持暫停。')
        return 2
    finally:
        if ready_fd is not None: os.close(ready_fd)


if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--root-pid',type=int,required=True); parser.add_argument('--root-created',type=float,required=True)
    parser.add_argument('--host-pid',type=int,required=True); parser.add_argument('--host-created',type=float,required=True)
    parser.add_argument('--ready-fd',type=int,required=True)
    args=parser.parse_args()
    raise SystemExit(guard(Identity(args.root_pid,args.root_created),Identity(args.host_pid,args.host_created),args.ready_fd))
