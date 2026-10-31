"""Real WebSocket SDK tests against a schema-checking in-process server.
Native Network.framework interoperability is separately covered by Swift TransportTests.
"""
import asyncio
import json
import sys
from pathlib import Path
from uuid import uuid4
import pytest
from websockets.asyncio.server import serve
ROOT=Path(__file__).resolve().parents[2]
sys.path.insert(0,str(ROOT/'packages/sdk-python'))
from maltose import Client,command,validate,MUPException
TOKEN='synthetic-test-token-0000000000000000'
def test_client_auth_correlation_context_events_and_reconnect():
    async def run():
        observed=[]
        async def handler(ws):
            auth=json.loads(await ws.recv());validate(auth)
            assert auth['payload']['token']==TOKEN
            sid=str(uuid4())
            await ws.send(json.dumps(dict(protocol='mup/0.3',request_id=auth['request_id'],ok=True,result=dict(session_id=sid,principal='agent.test'))))
            async for raw in ws:
                request=validate(json.loads(raw));assert request['session_id']==sid
                observed.append(request['name'])
                if request['name']=='ui.context.get':
                    result=dict(context_revision=4,captured_at='2026-10-29T04:00:00Z',active_app=None,focused_surface_id=None,focused_node_id=None,private_focus=False,fresh=True,resync_required=False,surfaces=[])
                elif request['name']=='ui.context.subscribe':result=dict(subscription_id=str(uuid4()),context_revision=4,resync_required=True)
                else:result={}
                await ws.send(json.dumps(dict(protocol='mup/0.3',request_id=request['request_id'],ok=True,result=result)))
                if request['name']=='ui.context.subscribe':
                    event=dict(protocol='mup/0.3',type='event',event_id=str(uuid4()),subscription_id=result['subscription_id'],source_agent_id='agent.test',surface_id=None,sequence=2,timestamp='2026-10-29T04:00:00Z',name='context.stale',context_revision=4,changes={'resync_required':True})
                    await ws.send(json.dumps(event));await ws.send(json.dumps(event))
        async with serve(handler,'127.0.0.1',0) as server:
            port=server.sockets[0].getsockname()[1]
            async with Client(TOKEN,f'ws://127.0.0.1:{port}') as client:
                await client.subscribe_context()
                generator=client.events()
                first=await asyncio.wait_for(anext(generator),2)
                assert first['type']=='resync'
                second=await asyncio.wait_for(anext(generator),2)
                assert second['name']=='context.stale'
                assert client.queue.empty() # duplicate event discarded
                snapshot=await client.reconnect()
                assert snapshot['context_revision']==4
                assert observed.count('ui.context.subscribe')==2
    asyncio.run(run())

def test_client_rejects_remote_endpoints_and_invalid_commands():
    with pytest.raises(ValueError):Client(TOKEN,'ws://example.com')
    with pytest.raises(Exception):command('ui.patch',{'surface_id':'x','expected_revision':0,'operations':[{'op':'eval'}]})
