"""Probe daemon-owned Docker work after a native root-group crash.

Uses only a fresh private fixture and its exact execution name/label. Never prunes
Docker or touches the running formal App. The pre-fix result is retained even
when the finally block successfully removes the test container.
"""
from pathlib import Path
import argparse
import json
import os
import queue
import shutil
import signal
import subprocess
import sys
import threading
import time
import uuid

from maltose.execution.docker_backend import DockerSandboxBackend
from maltose.runtime.processes import Identity

PROGRAM = '''import sys
from pathlib import Path
from types import SimpleNamespace
from maltose.agent.brain import EchoBrain
from maltose.execution import docker_backend
from maltose.execution.models import ExecutionRequest,ExecutionLimits
base=Path(sys.argv[1]);execution=sys.argv[2];fault=sys.argv[3]
workspace=base/'workspace';workspace.mkdir()
docker_backend.uuid=SimpleNamespace(uuid4=lambda:SimpleNamespace(hex=execution))
def run(self,text,context=None):
 backend=docker_backend.DockerSandboxBackend(image='python:3.12-slim')
 script="import time,signal;from pathlib import Path;signal.signal(signal.SIGTERM,signal.SIG_IGN);signal.signal(signal.SIGHUP,signal.SIG_IGN);p=Path('/execution/heartbeat');\\nwhile True:p.write_text(str(time.monotonic()));time.sleep(.03)"
 backend.execute(ExecutionRequest(('python','-c',script),limits=ExecutionLimits(timeout_seconds=3 if fault=='daemon-unreachable' else 60)),mounts=(),session_dir=workspace)
 (base/'after-backend').touch()
 return 'done'
EchoBrain.process=run
sys.argv=['maltose','--brain','echo','--native-text-only','--config',str(base/'none.toml')]
from maltose.desktop import main
main()
'''


HOST = """import json,subprocess,sys,time
child=subprocess.Popen([sys.executable,'-u','-c',sys.argv[1],*sys.argv[2:]],stdin=sys.stdin,stdout=sys.stdout,stderr=sys.stderr)
print(json.dumps({'fixtureRootPID':child.pid}),flush=True)
time.sleep(120)
"""


def probe(fault='root-group-crash', crash_at='running'):
    root=Path(__file__).resolve().parents[3]
    directory=root/'.cache/unification'/('native-docker-crash-'+str(uuid.uuid4()))
    directory.mkdir(mode=0o700)
    execution=uuid.uuid4().hex;name='maltose-exec-'+execution
    control=uuid.uuid4().hex;control_name='maltose-exec-'+control
    backend=DockerSandboxBackend(image='python:3.12-slim')
    backend._resolved_binary=shutil.which('docker')
    if backend._resolved_binary is None: raise RuntimeError('Installed Docker CLI is required')
    real_binary=backend._resolved_binary
    environment={**os.environ,'PYTHONPATH':str(root/'runtime')}
    if crash_at!='running' or fault=='daemon-unreachable':
        shim_dir=directory/'bin';shim_dir.mkdir()
        shim=shim_dir/'docker'
        shim.write_text('#!'+sys.executable+'\n'+
            'import os,sys,time\nfrom pathlib import Path\n'+
            'base=Path('+repr(str(directory))+')\n'+
            'if (base/"daemon-unavailable").exists() and sys.argv[1:3]==["container","ls"]:raise SystemExit(1)\n'+
            'if '+repr(crash_at!='running')+' and sys.argv[1:2]==['+repr('create' if crash_at=='creating' else 'start')+']:\n'+
            ' (base/"gate-entered").touch()\n'+
            ' while not (base/"gate-release").exists():time.sleep(.01)\n'+
            'os.execv('+repr(real_binary)+',['+repr(real_binary)+',*sys.argv[1:]])\n')
        shim.chmod(0o700)
        environment['PATH']=str(shim_dir)+os.pathsep+environment.get('PATH','')
    control_id=subprocess.run([real_binary,'run','--rm','--detach','--name',control_name,
        '--label','dev.maltose.execution-id='+control,'--network','none','--read-only',
        '--cap-drop','ALL','--security-opt','no-new-privileges:true','--pull','never',
        'python:3.12-slim','python','-c','import time;time.sleep(120)'],
        check=True,capture_output=True,text=True,timeout=10).stdout.strip()
    try:
        messages=queue.Queue();records=[]
        result=dict(schemaVersion=1,fault=fault,crashAt=crash_at,
                    containerIgnoresTermination=True,formalAppAffected=False,microphoneUsed=False)
        with (directory/'runtime.log').open('w') as log:
            host=fault=='host-crash'
            arguments=[sys.executable,'-u','-c',HOST,PROGRAM,str(directory),execution,fault] if host else [sys.executable,'-u','-c',PROGRAM,str(directory),execution,fault]
            child=subprocess.Popen(arguments,stdin=subprocess.PIPE,stdout=subprocess.PIPE,stderr=log,text=True,
                cwd=directory,env=environment)
            records=[Identity.read(child.pid)]
            def collect():
                for line in child.stdout:
                    try: messages.put(json.loads(line))
                    except ValueError: messages.put({'invalidProtocol':True})
            reader=threading.Thread(target=collect,daemon=True);reader.start()
            def send(identifier,method,params=None):
                child.stdin.write(json.dumps(dict(schemaVersion=1,requestID=identifier,method=method,params=params or {}))+'\n')
                child.stdin.flush()
            try:
                native=records[0]
                if host:
                    message=messages.get(timeout=10)
                    if 'fixtureRootPID' not in message: raise RuntimeError('Fixture host did not identify its child')
                    native=Identity.read(message['fixtureRootPID']);records.append(native)
                send('init','initialize');deadline=time.monotonic()+20
                while time.monotonic()<deadline:
                    message=messages.get(timeout=max(.01,deadline-time.monotonic()))
                    if message.get('invalidProtocol'): raise RuntimeError('Invalid native output')
                    if message.get('notification')=='ready': break
                else: raise TimeoutError('Native fixture did not become ready')
                send('run','submit_text',{'text':'run isolated container fixture'})
                heartbeat=directory/'workspace'/'heartbeat'
                marker=heartbeat if crash_at=='running' else directory/'gate-entered'
                deadline=time.monotonic()+12
                while not marker.exists() and child.poll() is None and time.monotonic()<deadline:time.sleep(.05)
                if not marker.exists():raise RuntimeError('Fault boundary never reached; inspect private diagnostics')
                time.sleep(.2)
                children=native.process().children(recursive=True)
                records.extend(Identity.read(p.pid) for p in children)
                if fault=='root-group-crash':os.killpg(native.pid,signal.SIGKILL)
                elif fault=='host-crash':child.kill()
                elif fault=='owner-eof':child.stdin.close()
                elif fault=='daemon-unreachable':(directory/'daemon-unavailable').touch()
                elif fault=='guardian-crash':
                    guardians=[p for p in children if 'maltose.runtime.lifetime' in p.cmdline()]
                    if len(guardians)!=1:raise RuntimeError('Expected exactly one lifetime guardian')
                    guardians[0].kill()
                else:raise ValueError('Unknown fixture fault')
                if crash_at=='creating':
                    if fault=='root-group-crash':
                        deadline=time.monotonic()+3
                        while native.process() is not None and time.monotonic()<deadline:time.sleep(.01)
                        if native.process() is not None:raise AssertionError('Root has not actually exited before lease check')
                        result['rootConfirmedGoneBeforeLeaseCheck']=True
                    from maltose.runtime.ownership import RuntimeLease
                    try:
                        with RuntimeLease(directory):pass
                    except RuntimeError:result['kernelLeaseHeldDuringCreate']=True
                    else:raise AssertionError('Creator must retain ownership after root crash')
                (directory/'gate-release').touch()
                deadline=time.monotonic()+12
                while any(r.process() is not None for r in records) and time.monotonic()<deadline:time.sleep(.05)
                before=heartbeat.read_bytes() if heartbeat.exists() else None
                time.sleep(.4)
                after=heartbeat.read_bytes() if heartbeat.exists() else None
                lookup=subprocess.run([real_binary,'container','ls','--all','--no-trunc',
                    '--filter','name=^/'+name+'$','--filter','label=dev.maltose.execution-id='+execution,'--format','{{.ID}}'],
                    capture_output=True,text=True,check=True,timeout=3)
                alive=subprocess.run([real_binary,'container','inspect','--format','{{.State.Running}}',control_id],
                    capture_output=True,text=True,check=True,timeout=3)
                result.update(allObservedProcessesStopped=all(r.process() is None for r in records),
                              containerAbsent=not lookup.stdout.strip(),heartbeatStopped=before==after,
                              heartbeatNeverStarted=before is None,unrelatedContainerRunning=alive.stdout.strip()=='true')
                if crash_at!='running' and heartbeat.exists():raise AssertionError('Creation fault unexpectedly started container work')
                if (directory/'after-backend').exists():raise AssertionError('Unconfirmed execution was accepted as a finished tool')
                requests=''.join(json.dumps(dict(schemaVersion=1,requestID=i,method=m))+'\n'
                    for i,m in [('recover','initialize'),('stop','shutdown')])
                if fault=='daemon-unreachable':
                    result['beforeRecovery']=dict(containerAbsent=result['containerAbsent'],heartbeatStopped=result['heartbeatStopped'])
                    if result['containerAbsent'] or result['heartbeatStopped']:raise AssertionError('Fixture did not preserve the daemon-side failure')
                    if child.wait(timeout=3)!=70:raise AssertionError('Unconfirmed cleanup must fail the runtime visibly')
                    blocked=subprocess.run([sys.executable,'-m','maltose.desktop','--native-text-only','--brain','echo',
                        '--config',str(directory/'none.toml')],input=requests,text=True,capture_output=True,
                        cwd=directory,env=environment,timeout=20)
                    if blocked.returncode==0 or '"notification": "ready"' in blocked.stdout:raise AssertionError('Pending writer did not block startup')
                    result['startupBlockedUntilDaemonRestored']=True
                    (directory/'daemon-unavailable').unlink()
                recovered=subprocess.run([sys.executable,'-m','maltose.desktop','--native-text-only','--brain','echo',
                    '--config',str(directory/'none.toml')],input=requests,text=True,capture_output=True,
                    cwd=directory,env=environment,timeout=20)
                if recovered.returncode:raise RuntimeError('Same-directory recovery failed; inspect fixture diagnostics')
                replies=[json.loads(line) for line in recovered.stdout.splitlines()]
                if not any(r.get('requestID')=='recover' and r.get('ok') for r in replies):raise RuntimeError('Recovery handshake missing')
                after_recovery=heartbeat.read_bytes() if heartbeat.exists() else None
                if fault=='daemon-unreachable':
                    stable=after_recovery;time.sleep(.2)
                    if heartbeat.read_bytes()!=stable:raise AssertionError('Recovered runtime left the container writer active')
                    if backend._owned_container_identity(name,execution) is not None:raise AssertionError('Recovery did not remove the exact owned container')
                    result.update(containerAbsent=True,heartbeatStopped=True)
                elif after_recovery!=after:raise AssertionError('Recovery replayed the interrupted container')
                final_control=subprocess.run([real_binary,'container','inspect','--format','{{.State.Running}}',control_id],
                    capture_output=True,text=True,check=True,timeout=3)
                result['unrelatedContainerRunning']=final_control.stdout.strip()=='true'
                result.update(sameDirectoryRestart=True,modelPromptSentOnRecovery=False,containerReplayedOnRecovery=False)
            finally:
                (directory/'gate-release').touch()
                for record in records:
                    process=record.process()
                    if process is not None:process.kill()
                child.wait(timeout=5)
                backend._remove_owned_container(name,execution)
                if not child.stdin.closed:child.stdin.close()
                reader.join(timeout=2);child.stdout.close()
        (directory/'result.json').write_text(json.dumps(result,indent=2)+'\n')
        return directory,result
    finally:
        backend._remove_owned_container(control_name,control,expected_identity=control_id)


if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--fault',choices=['root-group-crash','host-crash','owner-eof','guardian-crash','daemon-unreachable'],default='root-group-crash')
    parser.add_argument('--crash-at',choices=['running','creating','created'],default='running')
    args=parser.parse_args()
    directory,result=probe(args.fault,args.crash_at)
    print(json.dumps(dict(directory=str(directory),result=result)))
    raise SystemExit(0 if all(result.get(key) for key in ('allObservedProcessesStopped','containerAbsent','heartbeatStopped','unrelatedContainerRunning')) else 1)
