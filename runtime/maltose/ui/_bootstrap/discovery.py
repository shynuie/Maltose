import json
import os
import stat
from pathlib import Path
from .wire import WireClient,MUPFailure

def default_directory():return Path.home()/'Library/Application Support/MaltoseUIHost/discovery'
def secure_file(path):
    info=path.lstat()
    if not stat.S_ISREG(info.st_mode) or info.st_uid!=os.getuid() or info.st_mode&0o077:
        raise ValueError('Discovery file must be an owned 0600 regular file')
    return info

def discover(directory=None):
    directory=Path(directory) if directory else default_directory()
    if not directory.exists():return []
    info=directory.lstat()
    if not stat.S_ISDIR(info.st_mode) or info.st_uid!=os.getuid() or info.st_mode&0o077:
        raise ValueError('Discovery directory must be owned and private')
    results=[]
    for path in sorted(directory.glob('*.json'))[:64]:
        wire=None
        try:
            info=secure_file(path)
            if info.st_size>16384:continue
            record=json.loads(path.read_text())
            if record.get('protocol')!='mup/0.3':continue
            pid=int(record['pid'])
            if pid<=0:continue
            os.kill(pid,0)
            wire=WireClient(record['endpoint'],timeout=1)
            live=wire.request('host.discover')
            if live['instance_id']!=record['instance_id']:continue
            record['host_id']=live.get('host_id',record['instance_id'])
            results.append(record)
        except (OSError,ValueError,KeyError,TypeError,AttributeError,MUPFailure):continue
        finally:
            if wire:wire.close()
    return results
