"""Live, isolated app-server parent-death probe; never auto-approves requests."""
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
import uuid

import psutil


def identity(process):
    created=process.create_time()
    try: group=os.getpgid(process.pid)
    except ProcessLookupError: group=None
    return dict(pid=process.pid,created=created,processGroup=group)


def alive(record):
    try:
        process=psutil.Process(record['pid'])
        return process.create_time()==record['created'] and process.status()!=psutil.STATUS_ZOMBIE
    except psutil.NoSuchProcess: return False


def descendants(process):
    records=[]
    try: children=process.children(recursive=True)
    except psutil.NoSuchProcess: children=[]
    for child in [*children,process]:
        try: records.append(identity(child))
        except psutil.NoSuchProcess: pass
    return records


def stop_owned(records):
    remaining=[record for record in records if alive(record)]
    for record in remaining:
        try:
            process=psutil.Process(record['pid'])
            if process.create_time()==record['created']: process.kill()
        except psutil.NoSuchProcess: pass
    deadline=time.monotonic()+5
    while any(alive(record) for record in remaining) and time.monotonic()<deadline: time.sleep(.05)
    if any(alive(record) for record in remaining): raise RuntimeError('Owned probe processes did not stop')


class RPC:
    def __init__(self, process):
        self.process=process; self.messages=queue.Queue(); self.serial=0; self.events=[]; self.interactions=[]
        def read():
            try:
                for line in process.stdout:
                    if line.strip(): self.messages.put(json.loads(line))
            except (OSError,ValueError): pass
            finally: self.messages.put(None)
        self.reader=threading.Thread(target=read,daemon=True)
        self.reader.start()

    def send(self, value):
        self.process.stdin.write(json.dumps(value)+'\n'); self.process.stdin.flush()

    def next(self, timeout):
        value=self.messages.get(timeout=timeout)
        if value is None: raise RuntimeError('Codex closed its protocol during setup')
        if 'method' in value and 'id' in value:
            self.interactions.append(value['method'])
            self.send(dict(id=value['id'],error=dict(code=-32000,message='Lifecycle probe cannot approve human requests.')))
            raise RuntimeError('A human interaction was requested; probe cannot approve it')
        return value

    def call(self, method, params=None, timeout=30):
        self.serial+=1; identifier='probe-'+str(self.serial)
        self.send(dict(id=identifier,method=method,params=params or {}))
        deadline=time.monotonic()+timeout
        while time.monotonic()<deadline:
            value=self.next(max(.01,deadline-time.monotonic()))
            if value.get('id')==identifier:
                if 'error' in value: raise RuntimeError('Codex rejected '+method)
                return value.get('result')
            self.events.append(value)
        raise TimeoutError(method)

    def completed_turn(self, thread, timeout=180):
        deadline=time.monotonic()+timeout
        while time.monotonic()<deadline:
            for index,value in enumerate(self.events):
                if value.get('method')=='turn/completed' and value.get('params',{}).get('threadId')==thread:
                    event=self.events.pop(index)
                    if event['params']['turn']['status']!='completed': raise RuntimeError('Probe turn did not complete')
                    return
            self.events.append(self.next(max(.01,deadline-time.monotonic())))
        raise TimeoutError('turn completion')


def host(directory, executable, crash_at):
    os.umask(0o077)
    root=Path(__file__).resolve().parents[2]
    environment={**os.environ,'PYTHONPATH':str(root),'PYTHONDONTWRITEBYTECODE':'1'}
    # root is the runtime directory, not the developer checkout's old alias.
    server=None; owned=[]
    try:
        with (directory/'server.log').open('w') as log:
            server=subprocess.Popen([sys.executable,'-m','maltose.codex.runner',str(executable),'app-server'],
                stdin=subprocess.PIPE,stdout=subprocess.PIPE,stderr=log,text=True,cwd=directory,env=environment)
            owned=[identity(psutil.Process(server.pid))]
            (directory/'server-identity.json').write_text(json.dumps(owned[0]))
            rpc=RPC(server)
            rpc.call('initialize',dict(clientInfo=dict(name='maltose',title='Maltose lifecycle verification',version='0.7.0'),capabilities=dict(experimentalApi=True)))
            rpc.send(dict(method='initialized',params={}))
            account=rpc.call('account/read',dict(refreshToken=False))
            if account.get('requiresOpenaiAuth') and account.get('account') is None: raise RuntimeError('Codex sign-in required')
            models=rpc.call('model/list',dict(limit=100))['data']
            model=next(value['model'] for value in models if value.get('isDefault'))
            response=rpc.call('thread/start',dict(cwd=str(directory),model=model,sandbox='workspace-write',approvalPolicy='on-request',serviceName='maltose'))
            thread=response['thread']['id']
            prompt="""這是 Maltose 的宿主崩潰驗收，僅操作目前的隔離專案。
使用支援短時間 yield 的終端工具執行 python3 background.py。該腳本寫入自己的 background.pid 與 heartbeat，並持續 300 秒。
保持此程序由終端工具管理，不使用 shell 的 &、nohup 或自行脫離程序管理。不要修改腳本、不要自行停止程序，也不要等待五分鐘。
確認終端回傳仍在執行的 session/process ID 後，立即以簡短文字回報已啟動，讓宿主驗收自身退出時的清理。不要執行其他工作。"""
            rpc.call('turn/start',dict(threadId=thread,input=[dict(type='text',text=prompt)],clientUserMessageId='lifecycle-probe'))
            if crash_at=='background': rpc.completed_turn(thread)
            else:
                deadline=time.monotonic()+180
                while not (directory/'background.pid').exists() and time.monotonic()<deadline:
                    try: rpc.events.append(rpc.next(.05))
                    except queue.Empty: pass
                if not (directory/'background.pid').exists(): raise TimeoutError('Running fixture tool')
            terminals=rpc.call('thread/backgroundTerminals/list',dict(threadId=thread,limit=100))
            if terminals.get('nextCursor') or (crash_at=='background' and not terminals.get('data')): raise RuntimeError('Expected a bounded tracked terminal')
            turn_status=rpc.call('thread/read',dict(threadId=thread,includeTurns=True))['thread']['turns'][-1]['status']
            if crash_at=='running-tool' and turn_status!='inProgress': raise RuntimeError('Probe missed the active tool window')
            pid=int((directory/'background.pid').read_text())
            process=psutil.Process(pid)
            if server.pid not in [p.pid for p in process.parents()] or Path(process.cwd()).resolve()!=directory.resolve():
                raise RuntimeError('PID file is not a descendant in this fixture')
            command=process.cmdline()
            if not any(Path(part).name=='background.py' for part in command): raise RuntimeError('PID is not the fixture script')
            owned=descendants(psutil.Process(server.pid))
            if pid not in [record['pid'] for record in owned]: raise RuntimeError('Background identity was not captured')
            result=dict(server=identity(psutil.Process(server.pid)),background=identity(process),owned=owned,
                threadID=thread,model=model,trackedTerminals=len(terminals['data']),humanInteractions=rpc.interactions,crashAt=crash_at,turnStatusBeforeCrash=turn_status)
            (directory/'ready.json').write_text(json.dumps(result))
            while True: time.sleep(1)
    finally:
        # SIGKILL bypasses this block deliberately. The outer probe retains
        # independently captured identities and cleans up a failed experiment.
        if server is not None:
            if server.poll() is None: owned=descendants(psutil.Process(server.pid))
            stop_owned(owned)
            if 'rpc' in locals(): rpc.reader.join(timeout=5)


def recover(directory, executable):
    directory=directory.resolve()
    if directory.parent.name!='parent-crash' or not (directory/'.git').is_dir():
        raise ValueError('Only an isolated parent-crash fixture can be recovered')
    if directory.stat().st_uid!=os.getuid() or directory.stat().st_mode & 0o077:
        raise PermissionError('Probe directory must be owner-only')
    data=json.loads((directory/'ready.json').read_text())
    if not isinstance(data.get('threadID'),str) or not data['threadID']: raise ValueError('Probe thread identity is missing')
    if any(alive(record) for record in data['owned']): raise RuntimeError('Old probe processes must stop before recovery')
    heartbeat=(directory/'heartbeat').read_text()
    root=Path(__file__).resolve().parents[2]
    environment={**os.environ,'PYTHONPATH':str(root),'PYTHONDONTWRITEBYTECODE':'1'}
    with (directory/'recovery.log').open('w') as log:
        process=subprocess.Popen([sys.executable,'-m','maltose.codex.runner',str(executable),'app-server'],
            stdin=subprocess.PIPE,stdout=subprocess.PIPE,stderr=log,text=True,cwd=directory,env=environment)
        recovery_owned=descendants(psutil.Process(process.pid))
        try:
            rpc=RPC(process)
            rpc.call('initialize',dict(clientInfo=dict(name='maltose',title='Maltose recovery verification',version='0.7.0'),capabilities=dict(experimentalApi=True)))
            rpc.send(dict(method='initialized',params={}))
            response=rpc.call('thread/resume',dict(threadId=data['threadID'],cwd=str(directory),sandbox='workspace-write',approvalPolicy='on-request',excludeTurns=True))
            if response['thread']['id']!=data['threadID'] or Path(response['thread']['cwd']).resolve()!=directory:
                raise RuntimeError('Recovery did not preserve the same thread and workspace')
            history=rpc.call('thread/read',dict(threadId=data['threadID'],includeTurns=True))
            time.sleep(.5)
            terminals=rpc.call('thread/backgroundTerminals/list',dict(threadId=data['threadID'],limit=100))
            replayed=bool(terminals.get('data')) or (directory/'heartbeat').read_text()!=heartbeat or any(
                event.get('method')=='turn/started' for event in rpc.events)
            if replayed: raise RuntimeError('Thread recovery replayed work without new user intent')
            rpc.call('thread/archive',dict(threadId=data['threadID']))
            deadline=time.monotonic()+5
            archived=any(event.get('method')=='thread/archived' and event.get('params',{}).get('threadId')==data['threadID'] for event in rpc.events)
            while not archived and time.monotonic()<deadline:
                event=rpc.next(max(.01,deadline-time.monotonic()))
                archived=event.get('method')=='thread/archived' and event.get('params',{}).get('threadId')==data['threadID']
            if not archived: raise RuntimeError('Probe thread archive was not confirmed')
            result=dict(resumedSameThread=True,preservedWorkspace=True,backgroundWorkReplayed=False,modelPromptSent=False,
                recoveredTurnStatuses=[turn['status'] for turn in history['thread']['turns']],fixtureThreadArchived=True)
            (directory/'recovery-result.json').write_text(json.dumps(result,indent=2)+'\n')
            return result
        finally:
            if process.poll() is None: recovery_owned+=descendants(psutil.Process(process.pid))
            if process.stdin: process.stdin.close()
            try: process.wait(timeout=10)
            except subprocess.TimeoutExpired: stop_owned(recovery_owned); process.wait(timeout=5)
            if 'rpc' in locals():
                rpc.reader.join(timeout=5)
                if rpc.reader.is_alive():
                    stop_owned(recovery_owned); rpc.reader.join(timeout=2)
                if rpc.reader.is_alive(): raise RuntimeError('Recovery protocol reader did not finish')
            if process.stdout: process.stdout.close()


def probe(executable, crash_at, fault):
    os.umask(0o077)
    project=Path(__file__).resolve().parents[3]
    directory=project/'.cache/unification/parent-crash'/str(uuid.uuid4())
    directory.mkdir(parents=True,mode=0o700)
    (directory/'background.py').write_text("import os,time,signal\nsignal.signal(signal.SIGHUP,signal.SIG_IGN)\nfrom pathlib import Path\nPath('background.pid').write_text(str(os.getpid()))\nend=time.monotonic()+300\nwhile time.monotonic()<end:\n Path('heartbeat').write_text(str(time.monotonic_ns()))\n time.sleep(.1)\n")
    for args in (['init','--quiet'],['add','background.py'],['-c','user.name=Fixture','-c','user.email=fixture@example.invalid','-c','core.hooksPath=/dev/null','commit','--quiet','-m','fixture']):
        subprocess.run(['/usr/bin/git','-C',str(directory),*args],check=True,capture_output=True)
    records=[]; result=None
    with (directory/'host.log').open('w') as log:
        parent=subprocess.Popen([sys.executable,str(Path(__file__).resolve()),'--child',str(directory),'--executable',str(executable),'--crash-at',crash_at],
            stdin=subprocess.DEVNULL,stdout=log,stderr=log,env=os.environ.copy())
        try:
            deadline=time.monotonic()+210
            while not (directory/'ready.json').exists() and time.monotonic()<deadline:
                if parent.poll() is not None: raise RuntimeError('Probe host setup failed; inspect private host.log in '+str(directory))
                records+=descendants(psutil.Process(parent.pid))
                records=list({(item['pid'],item['created']):item for item in records if item['pid']!=parent.pid}.values())
                time.sleep(.1)
            if not (directory/'ready.json').exists(): raise TimeoutError('Probe host setup')
            data=json.loads((directory/'ready.json').read_text()); records+=data['owned']
            records=list({(item['pid'],item['created']):item for item in records}.values())
            if not all(alive(data[key]) for key in ('server','background')): raise RuntimeError('Probe processes were not live before host crash')
            if fault=='server-crash':
                if os.getpgid(data['server']['pid'])!=data['server']['pid']: raise RuntimeError('Server has no exclusive owned process group')
                os.killpg(data['server']['pid'],signal.SIGKILL)
            else:
                parent.kill(); parent.wait(timeout=5)
            deadline=time.monotonic()+10
            while any(alive(record) for record in records) and time.monotonic()<deadline: time.sleep(.05)
            before=(directory/'heartbeat').read_text(); time.sleep(.5)
            result=dict(fault=fault,ignoresHangup=True,crashAt=crash_at,turnStatusBeforeCrash=data['turnStatusBeforeCrash'],hostKilled=fault=='host-crash',hostAliveDuringObservation=parent.poll() is None,serverStopped=not alive(data['server']),backgroundStopped=not alive(data['background']),
                allCapturedProcessesStopped=not any(alive(record) for record in records),heartbeatStopped=(directory/'heartbeat').read_text()==before,
                capturedProcesses=len(records),trackedTerminals=data['trackedTerminals'],humanInteractions=data['humanInteractions'],model=data['model'])
            (directory/'result.json').write_text(json.dumps(result,indent=2)+'\n')
        finally:
            if parent.poll() is None:
                records+=descendants(psutil.Process(parent.pid)); parent.kill(); parent.wait(timeout=5)
            if not records and (directory/'server-identity.json').exists():
                server=json.loads((directory/'server-identity.json').read_text())
                if alive(server): records=descendants(psutil.Process(server['pid']))
            stop_owned(records)
    if result and all(result[key] for key in ('serverStopped','backgroundStopped','allCapturedProcessesStopped','heartbeatStopped')):
        result['recovery']=recover(directory,executable)
        (directory/'result.json').write_text(json.dumps(result,indent=2)+'\n')
    print(json.dumps(dict(directory=str(directory),result=result)))
    return bool(result and all(result[key] for key in ('serverStopped','backgroundStopped','allCapturedProcessesStopped','heartbeatStopped')))


if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--executable',type=Path,default=Path('/opt/homebrew/bin/codex'))
    parser.add_argument('--child',type=Path)
    parser.add_argument('--recover',type=Path)
    parser.add_argument('--fault',choices=['host-crash','server-crash'],default='host-crash')
    parser.add_argument('--crash-at',choices=['background','running-tool'],default='background')
    args=parser.parse_args()
    if not args.executable.is_absolute() or not os.access(args.executable,os.X_OK): raise ValueError('An installed absolute Codex executable is required')
    if args.child: host(args.child,args.executable,args.crash_at)
    elif args.recover: print(json.dumps(recover(args.recover,args.executable)))
    else: raise SystemExit(0 if probe(args.executable,args.crash_at,args.fault) else 1)
