from __future__ import annotations
import json
import logging
import math
import re
import threading
import time
from pathlib import Path
from typing import Any
from ._bootstrap import Bootstrap
logger=logging.getLogger(__name__)

def _mup_id(value,fallback):
    text=re.sub(r'[^A-Za-z0-9._-]+','-',str(value or fallback)).strip('-.')[:128]
    if not text or not text[0].isalnum():text='n-'+text
    return text[:128]

def _finite_number(value,default,maximum=4096):
    if isinstance(value,bool):return default
    try:number=float(value)
    except (TypeError,ValueError,OverflowError):return default
    if not math.isfinite(number):return default
    return min(maximum,max(0,number))

def _canvas_document(block):
    raw=block.get('elements',[])
    if not isinstance(raw,list):raw=[]
    elements=[];used=set()
    for index,item in enumerate(raw[:256]):
        if not isinstance(item,dict):continue
        source_type=item.get('type')
        shape=item.get('shape',item.get('primitive'))
        if source_type=='text':kind='canvas.text'
        elif source_type=='node':
            kind={'rect':'canvas.rect','rectangle':'canvas.rect','ellipse':'canvas.ellipse','circle':'canvas.ellipse','triangle':'canvas.triangle'}.get(shape,'canvas.rect')
        else:continue
        x=_finite_number(item.get('x'),0);y=_finite_number(item.get('y'),0)
        width=max(1,_finite_number(item.get('width'),120));height=max(1,_finite_number(item.get('height'),48))
        label=str(item.get('label') or item.get('id') or '')[:2048]
        color=item.get('color')
        if not isinstance(color,str) or not re.fullmatch(r'#[0-9A-Fa-f]{6}',color):color='#E5E7EB'
        node_id=_mup_id(item.get('id'),f'element-{index+1}')
        base=node_id;suffix=2
        while node_id in used:
            tail=f'-{suffix}';node_id=base[:128-len(tail)]+tail;suffix+=1
        used.add(node_id)
        elements.append({'node_id':node_id,'type':kind,'props':{'x':x,'y':y,'width':width,'height':height,'label':label,'color':color}})
    requested_width=block.get('width');requested_height=block.get('height')
    width=_finite_number(requested_width,max(640,max((e['props']['x']+e['props']['width'] for e in elements),default=0))) or 640
    height=_finite_number(requested_height,max(480,max((e['props']['y']+e['props']['height'] for e in elements),default=0))) or 480
    for element in elements:
        p=element['props'];p['x']=min(p['x'],width-1);p['y']=min(p['y'],height-1)
        p['width']=min(p['width'],width-p['x']);p['height']=min(p['height'],height-p['y'])
    return {'node_id':'scene','type':'canvas','props':{'width':width,'height':height},'children':elements}

class MaltoseBridge:
    def __init__(self,event_hub,*,agent_id='agent.myagent',name='Maltose',directory=None,state_root=None,bootstrap_factory=Bootstrap):
        self.hub=event_hub;self.agent=None;self.brain=None;self.registry=None
        self.stop=threading.Event();self.thread=None;self.registered=set()
        self._last_state=None;self._speech_active=False;self._model_active=False
        self.bootstrap=bootstrap_factory(agent_id=agent_id,name=name,directory=directory,state_root=state_root,on_tools=self._tools_ready,on_notification=self._notification,on_status=self._status)
    def tools(self):
        from maltose.agent.capabilities import CapabilityTool
        return [CapabilityTool('maltose_connect','Find a local Maltose UI and request native user approval. Installs only the verified UI toolkit in a separate uv environment. Never ask the user for a port or credential.',{'type':'object','properties':{'instance_id':{'type':'string'}},'additionalProperties':False},lambda a:self.bootstrap.connect(a.get('instance_id')))]
    def attach(self,agent,brain=None):
        self.agent=agent;self.brain=brain
        self.registry=getattr(brain,'tools',None)
    def _tools_ready(self,tools):
        if not self.registry:return
        from maltose.agent.capabilities import CapabilityTool
        for tool in tools:
            name=tool['name']
            if not name.startswith('maltose_') or len(name)>64:raise ValueError('Unexpected toolkit tool namespace')
            if self.registry.has(name):continue
            def handler(arguments,tool_name=name):
                if tool_name in ('maltose_context','maltose_resolve') and not self._identity_verified():
                    return {'error':'speaker_verification_required','message':'Private UI context follows the existing Maltose speaker verification policy.'}
                try:
                    return self.bootstrap.call(tool_name,arguments)
                except Exception as error:
                    code=getattr(error,'code',None)
                    logger.warning('maltose_tool_failed tool=%s code=%s error=%s',tool_name,code or 'bridge_error',type(error).__name__)
                    result={'error':'ui_tool_failed','tool':tool_name,'message':'Maltose could not complete this UI operation.'}
                    if code:
                        result['code']=str(code)[:64]
                        result['reason']=str(error)[:256]
                    return result
            self.registry.register(name,tool['description'],tool['parameters'],handler)
            self.registered.add(name)
    def _identity_verified(self):
        # Do not turn possession of an agent connection token into human speaker authentication.
        return bool(self.brain and self.brain._identity_is_known())
    def context(self):
        if not self._identity_verified():return {'available':False,'reason':'speaker_verification_required'}
        try:return self.bootstrap.context()
        except Exception:return {'available':False,'reason':'ui_disconnected'}
    def _status(self,value):
        # Verification code is public pairing metadata. Tokens never enter EventHub or logs.
        self.hub.publish('maltose_connection',value)
        if value.get('state')=='waiting_for_approval':logger.info('maltose_pairing_waiting verification_code=%s',value.get('verification_code'))
        elif value.get('state')=='error':logger.warning('maltose_connection_failed code=%s',value.get('code'))
    def _notification(self,value):
        kind=value.get('notification')
        if kind=='input' and self.agent and value['value'].get('kind')=='text':self.agent.submit_text(value['value']['text'])
        elif kind=='action':
            event=value['value'];self.hub.publish('ui_action',event.get('changes',{}))
            if self.agent and event.get('changes',{}).get('action_id')=='analyze_selection':
                self.agent.submit_text('請分析我在 Maltose 中目前選取的圖表區間；先取得授權的新鮮 UI 情境，資訊不足時請詢問。')
        elif kind in ('disconnected','context_invalidated'):self.hub.publish('maltose_connection',{'state':'disconnected'})
    def _runtime(self,event,data):
        if event=='model_started':self._model_active=True
        elif event in ('model_finished','model_failed'):self._model_active=False
        elif event=='speech_started':self._speech_active=True
        elif event=='speech_finished':self._speech_active=False
        try:self.bootstrap.runtime(event,data)
        except Exception:pass # UI loss cannot interrupt speech, tools, memory or a model call.
    def start(self):
        subscription=self.hub.subscribe();self.bootstrap.start()
        def run():
            # EventHub subscriptions are bounded and non-blocking to Agent producers.
            for event in subscription:
                if self.stop.is_set():break
                try:self._forward(event.type,event.payload)
                except Exception:logger.debug('maltose_event_forward_failed')
        def heartbeat():
            while not self.stop.wait(2):
                if self.agent:self._runtime('state_changed',{'state':self.agent.state.value})
                self._runtime('heartbeat',{})
                self._runtime('model_started' if self._model_active else 'model_finished',{})
                self._runtime('speech_started' if self._speech_active else 'speech_finished',{})
        self.subscription=subscription
        self.thread=threading.Thread(target=run,daemon=True);self.thread.start()
        threading.Thread(target=heartbeat,daemon=True).start()
    def _forward(self,event,payload):
        if event=='ui_block':self._present(payload);return
        if event=='assistant_message':
            mid='reply-'+str(time.monotonic_ns());self._runtime('assistant_start',{'message_id':mid});self._runtime('assistant_end',{'message_id':mid,'content':str(payload.get('content',''))[-16384:]});return
        allowed={'state_changed':{'state'},'model_started':set(),'model_finished':set(),'model_failed':set(),'tool_started':{'tool'},'tool_finished':{'tool'},'tool_failed':{'tool'},'speech_started':set(),'speech_finished':set(),'assistant_start':{'message_id'},'assistant_delta':{'message_id','content'},'assistant_end':{'message_id','content'},'user_message':{'content'},'task_progress':{'detail','progress'},'error':{'detail'}}
        if event not in allowed:return
        data={k:v for k,v in payload.items() if k in allowed[event]}
        for field in ('content','detail'):
            if field in data:data[field]=str(data[field])[-16384:]
        self._runtime(event,data)
    def _present(self,block):
        kind=block.get('block_type');identifier=str(block.get('block_id','view')).replace(':','-')[:100]
        if kind=='ui_progress':
            detail=str(block.get('message') or block.get('detail') or block.get('title') or '任務執行中')
            self._runtime('task_progress',{'detail':detail[:16384]});return
        if kind=='ui_canvas':
            root=_canvas_document(block)
            identifier=_mup_id(block.get('scene_id') or block.get('block_id') or 'canvas','canvas')[:120]
        elif kind=='ui_table':
            columns=block.get('columns',[]);rows=block.get('rows',[])
            if rows and isinstance(rows[0],dict):rows=[[r.get(c) for c in columns] for r in rows]
            root={'node_id':'content','type':'table','props':{'columns':columns,'rows':rows}}
        else:
            text=block.get('markdown') or block.get('content') or block.get('body') or block.get('message') or json.dumps(block,ensure_ascii=False)
            root={'node_id':'content','type':'text','props':{'text':str(text)[:16384]}}
        payload={'surface_id':'myagent-'+identifier,'title':str(block.get('title') or 'Maltose')[:256],'document':{'root':root}}
        try:self.bootstrap.call('maltose_show',payload)
        except Exception:logger.debug('maltose_presentation_unavailable')
    def close(self):
        self.stop.set()
        if hasattr(self,'subscription'):self.subscription.close()
        self.bootstrap.close()
