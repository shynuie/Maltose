import json
import os
import queue
import re
import secrets
import subprocess
import threading
import time
import uuid
from pathlib import Path
from .discovery import discover,secure_file
from .installer import install,verify_artifact
from .wire import WireClient,MUPFailure

class SidecarClient:
    def __init__(self,python,endpoint,token,on_notification=None):
        self.process=subprocess.Popen([str(python),'-u','-m','maltose_runtime'],stdin=subprocess.PIPE,stdout=subprocess.PIPE,stderr=subprocess.DEVNULL,text=True,bufsize=1)
        self.pending={};self.lock=threading.Lock();self.on_notification=on_notification
        self.closed=False
        threading.Thread(target=self._read,daemon=True).start()
        try:self.initialized=self.request('initialize',{'endpoint':endpoint,'token':token},timeout=10)
        except Exception:
            self.close()
            raise
    def _read(self):
        try:
            while True:
                line=self.process.stdout.readline(1_048_577)
                if not line:break
                if len(line)>1_048_576:raise ValueError('Oversized sidecar reply')
                value=json.loads(line)
                if 'notification' in value:
                    if self.on_notification:self.on_notification(value)
                    if value['notification']=='disconnected':
                        self.process.terminate()
                        break
                    continue
                with self.lock:target=self.pending.get(value.get('id'))
                if target:target.put(value)
        except Exception:pass
        finally:
            self.closed=True
            with self.lock:waiting=list(self.pending.values())
            for target in waiting:
                try:target.put_nowait({'error':{'code':'disconnected','message':'UI worker disconnected'}})
                except queue.Full:pass
    def request(self,op,args=None,timeout=10):
        rid=str(uuid.uuid4());response=queue.Queue(maxsize=1)
        with self.lock:
            if self.closed or self.process.poll() is not None:raise ConnectionError('UI worker unavailable')
            self.pending[rid]=response
            self.process.stdin.write(json.dumps({'id':rid,'op':op,'args':args or {}},ensure_ascii=False,separators=(',',':'))+'\n');self.process.stdin.flush()
        try:
            value=response.get(timeout=timeout)
            if 'error' in value:raise MUPFailure(value['error'])
            return value['result']
        finally:
            with self.lock:self.pending.pop(rid,None)
    def close(self):
        try:self.request('close',timeout=1)
        except Exception:pass
        self.closed=True
        if self.process.poll() is None:
            self.process.terminate()
            try:self.process.wait(timeout=2)
            except subprocess.TimeoutExpired:self.process.kill();self.process.wait(timeout=2)

class Bootstrap:
    def __init__(self,agent_id='agent.myagent',name='MyAgent',directory=None,state_root=None,on_tools=None,on_notification=None,on_status=None):
        if not re.fullmatch(r'[A-Za-z0-9][A-Za-z0-9._-]{0,127}',agent_id):raise ValueError('Invalid agent ID')
        self.agent_id=agent_id;self.name=name;self.directory=directory
        base=Path(state_root) if state_root else Path.home()/'Library/Application Support/MaltoseAgentBridge'
        self.root=base/agent_id;self.root.mkdir(parents=True,exist_ok=True,mode=0o700);os.chmod(self.root,0o700)
        if self.root.is_symlink():raise ValueError('Agent state root cannot be a symlink')
        self.on_tools=on_tools;self.on_notification=on_notification;self.on_status=on_status
        self.worker=None;self.state='disconnected';self.last_error=None;self.stopping=threading.Event();self.connect_lock=threading.Lock()
    def _status(self,state,**extra):
        self.state=state
        if self.on_status:self.on_status({'state':state,**extra})
    def start(self):
        def monitor():
            while not self.stopping.is_set():
                if (not self.worker or self.worker.closed) and self.state not in ('denied','approval_expired','choose_ui','authorization_required'):
                    self.connect()
                self.stopping.wait(5)
        threading.Thread(target=monitor,daemon=True).start()
    def _credentials(self):
        path=self.root/'credentials.json'
        if not path.exists():return {}
        secure_file(path);return json.loads(path.read_text())
    def _save_credentials(self,value):
        path=self.root/'credentials.json';temp=self.root/('.credentials-'+str(uuid.uuid4()))
        fd=os.open(temp,os.O_WRONLY|os.O_CREAT|os.O_EXCL,0o600)
        with os.fdopen(fd,'w') as f:json.dump(value,f)
        os.replace(temp,path)
    def connect(self,instance_id=None):
        if not self.connect_lock.acquire(blocking=False):return {'state':self.state}
        wire=None
        try:
            if self.worker and not self.worker.closed:return {'state':'connected','principal':self.agent_id}
            self._status('discovering')
            services=discover(self.directory)
            if instance_id:services=[s for s in services if s['instance_id']==instance_id]
            if not services:self._status('unavailable');return {'state':'unavailable'}
            if len(services)!=1:
                self._status('choose_ui');return {'state':'choose_ui','instances':[{'name':s['name'],'instance_id':s['instance_id']} for s in services]}
            service=services[0];wire=WireClient(service['endpoint'])
            credentials=self._credentials();host_id=service['host_id'];token=credentials.get(host_id)
            if token:
                try:
                    auth=wire.authenticate(token)
                    if auth['principal']!=self.agent_id:raise ValueError('Cached principal mismatch')
                except Exception:
                    wire.close();wire=None;self._status('authorization_required');return {'state':'authorization_required'}
            if not token:
                claim=secrets.token_urlsafe(32)
                pairing=wire.request('host.pair.request',{'name':self.name,'agent_id':self.agent_id,'claim':claim})
                self._status('waiting_for_approval',verification_code=pairing['verification_code'])
                deadline=time.monotonic()+120
                while not self.stopping.wait(.5) and time.monotonic()<deadline:
                    answer=wire.request('host.pair.poll',{'pairing_id':pairing['pairing_id'],'claim':claim})
                    if answer['status']=='approved':token=answer['token'];break
                    if answer['status'] in ('denied','claimed'):self._status('denied');return {'state':'denied'}
                if not token:self._status('approval_expired');return {'state':self.state}
                auth=wire.authenticate(token)
                if auth['principal']!=self.agent_id:raise ValueError('Paired principal mismatch')
            offer=wire.request('host.toolkit.get')
            verify_artifact(offer) # pinned bootstrap publisher key, before any code installation
            credentials[host_id]=token;self._save_credentials(credentials)
            self._status('installing')
            python=install(offer,self.root/'runtimes')
            credentials[host_id]=token;self._save_credentials(credentials)
            worker=SidecarClient(python,service['endpoint'],token,on_notification=self.on_notification)
            if worker.initialized['principal']!=self.agent_id:worker.close();raise ValueError('Worker principal mismatch')
            self.worker=worker
            if self.on_tools:self.on_tools(worker.initialized['tools'])
            self._status('connected');return {'state':'connected','principal':self.agent_id}
        except Exception as error:
            self.last_error=getattr(error,'code',type(error).__name__)
            self._status('error',code=self.last_error)
            return {'state':'error','code':self.last_error}
        finally:
            if wire:wire.close()
            self.connect_lock.release()
    def request(self,op,args=None):
        worker=self.worker
        if not worker or worker.closed:raise ConnectionError('UI is not connected')
        return worker.request(op,args)
    def call(self,name,arguments):return self.request('call',{'name':name,'arguments':arguments})
    def context(self):return self.request('context')
    def runtime(self,event,data):return self.request('runtime',{'event':event,'data':data})
    def close(self):
        self.stopping.set()
        if self.worker:self.worker.close()
        self._status('disconnected')
