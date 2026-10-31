"""Long-lived stdio sidecar. stdout is protocol only; credentials never become tool results."""
import json
import sys
import threading
import time
import uuid
from .wire import WireClient,MUPFailure
from .tools import TOOLS,COMMANDS,show_surface
out_lock=threading.Lock();wire=None;run_id=str(uuid.uuid4());sequence=0;runtime_lock=threading.Lock();stop=threading.Event()
def send(value):
    with out_lock:sys.stdout.write(json.dumps(value,ensure_ascii=False,separators=(',',':'))+'\n');sys.stdout.flush()
def publish(kind,data):
    global sequence
    with runtime_lock:
        sequence+=1
        return wire.request('agent.runtime.publish',dict(run_id=run_id,sequence=sequence,event=kind,data=data))
def drain_events():
    with wire.lock:
        events=wire.events;wire.events=[]
    for event in events:
        if event['name']=='ui.action':send({'notification':'action','value':event})
        elif event['name']=='context.permission_changed':send({'notification':'context_invalidated'})
def polling():
    while not stop.wait(.3):
        try:
            # Parent runtime sends heartbeats. A live sidecar alone must not claim its Agent is healthy.
            for value in wire.request('agent.input.poll'):send({'notification':'input','value':value})
            drain_events()
        except Exception:send({'notification':'disconnected'});stop.set();return

def main():
    global wire
    if '--self-test' in sys.argv:
        assert len(TOOLS)==6;print('UI runtime healthy');return
    try:
        for line in sys.stdin:
            if len(line)>1_048_576:raise ValueError('Oversized sidecar command')
            request=json.loads(line);rid=request['id']
            try:
                op=request['op'];args=request.get('args',{})
                if op=='initialize':
                    if wire is not None:raise ValueError('Already initialized')
                    wire=WireClient(args['endpoint'],timeout=5);auth=wire.authenticate(args['token'])
                    wire.request('events.subscribe')
                    result={'tools':TOOLS,'principal':auth['principal']}
                    threading.Thread(target=polling,daemon=True).start()
                elif op=='call':
                    name=args['name']
                    if name not in COMMANDS:raise ValueError('Unknown UI tool')
                    payload=args.get('arguments',{})
                    if name=='maltose_context':payload={**payload,'max_age_ms':5000}
                    if name=='maltose_show':
                        result=show_surface(wire,payload)
                    else:result=wire.request(COMMANDS[name],payload)
                elif op=='context':result=wire.request('ui.context.get',{'max_age_ms':5000})
                elif op=='runtime':result=publish(args['event'],args.get('data',{}))
                elif op=='close':send({'id':rid,'result':{'closed':True}});return
                else:raise ValueError('Unknown sidecar operation')
                # Actions stay scoped by authenticated Host subscription and are passed back as input.
                drain_events()
                send({'id':rid,'result':result})
            except Exception as error:
                send({'id':rid,'error':{'code':getattr(error,'code','bridge_error'),'message':str(error) if isinstance(error,(ValueError,MUPFailure)) else 'UI worker operation failed'}})
    finally:
        stop.set()
        if wire:wire.close()
if __name__=='__main__':main()
