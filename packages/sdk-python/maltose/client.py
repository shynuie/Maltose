import asyncio
import contextlib
import json
from uuid import uuid4
from urllib.parse import urlparse
import websockets
from . import command, validate

class MUPException(Exception):
    def __init__(self, error):
        super().__init__(error['message'])
        self.code = error['code']
        self.details = error.get('details', {})

class Client:
    """A client belongs to one authenticated principal. Never log its token."""
    def __init__(self, token, url='ws://127.0.0.1:8765'):
        parsed=urlparse(url)
        if parsed.scheme!='ws' or parsed.hostname!='127.0.0.1':
            raise ValueError('MUP only connects to IPv4 loopback')
        self.token=token; self.url=url; self.session_id=str(uuid4())
        self.socket=None; self.reader=None; self.pending={}
        self.queue=asyncio.Queue(maxsize=128); self.seen=set(); self.sequences={}
        self.subscriptions=[]; self.context_revision=0; self.needs_resync=True
        self.context_cache=None
    async def __aenter__(self): return await self.connect()
    async def __aexit__(self,*_): await self.close()
    async def connect(self):
        self.socket=await websockets.connect(self.url,max_size=1_048_576,max_queue=16,open_timeout=5)
        auth=command('host.authenticate',{'token':self.token},session_id=self.session_id)
        await self.socket.send(json.dumps(auth))
        try:
            reply=validate(json.loads(await asyncio.wait_for(self.socket.recv(),5)),'response')
            if reply['request_id'] != auth['request_id']: raise ValueError('Authentication correlation mismatch')
            if not reply['ok']: raise MUPException(reply['error'])
            self.session_id=reply['result']['session_id']
            self.principal=reply['result']['principal']
        except BaseException:
            await self.socket.close();raise
        self.reader=asyncio.create_task(self._read())
        return self
    async def close(self):
        self.needs_resync=True;self.context_cache=None
        if self.reader:
            self.reader.cancel()
            with contextlib.suppress(asyncio.CancelledError): await self.reader
            self.reader=None
        if self.socket: await self.socket.close();self.socket=None
        for future in self.pending.values():
            if not future.done(): future.set_exception(ConnectionError('Disconnected'))
        self.pending.clear()
    async def request(self,name,payload=None,*,idempotency_key=None,request_id=None):
        if not self.socket: raise ConnectionError('Not connected')
        msg=command(name,payload,session_id=self.session_id,request_id=request_id,idempotency_key=idempotency_key)
        rid=msg['request_id']
        if rid in self.pending: raise ValueError('Duplicate in-flight request')
        future=asyncio.get_running_loop().create_future();self.pending[rid]=future
        try:
            await self.socket.send(json.dumps(msg))
            reply=await asyncio.wait_for(future,10)
            if not reply['ok']: raise MUPException(reply['error'])
            return reply['result']
        finally: self.pending.pop(rid,None)
    async def _read(self):
        try:
            async for raw in self.socket:
                msg=json.loads(raw)
                if msg.get('type')=='event':
                    validate(msg,'event')
                    eid=msg['event_id']
                    if eid in self.seen: continue
                    if len(self.seen)>=2048: self.seen.clear()
                    self.seen.add(eid)
                    sid=msg['subscription_id'];seq=msg['sequence']
                    old=self.sequences.get(sid,0)
                    if seq<=old: continue
                    if seq!=old+1: self.needs_resync=True
                    self.sequences[sid]=seq
                    if msg['name'] in ('context.stale','context.permission_changed'):
                        self.context_cache=None;self.needs_resync=True
                    if self.queue.full():
                        while not self.queue.empty(): self.queue.get_nowait()
                        self.needs_resync=True
                    self.queue.put_nowait(msg)
                else:
                    validate(msg,'response')
                    future=self.pending.get(msg['request_id'])
                    if future and not future.done(): future.set_result(msg)
        except asyncio.CancelledError: raise
        except Exception:
            self.needs_resync=True;self.context_cache=None
        finally:
            self.needs_resync=True;self.context_cache=None
            for future in list(self.pending.values()):
                if not future.done():future.set_exception(ConnectionError('Connection ended; reconnect and resync'))
    async def context(self,**filters):
        snapshot=await self.request('ui.context.get',filters)
        validate(snapshot,'context')
        self.context_revision=snapshot['context_revision'];self.context_cache=snapshot
        self.needs_resync=False
        return snapshot
    async def subscribe_context(self,**filters):
        result=await self.request('ui.context.subscribe',{**filters,'since_context_revision':self.context_revision})
        if filters not in self.subscriptions:self.subscriptions.append(filters.copy())
        self.needs_resync |= result['resync_required']
        return result
    async def reconnect(self):
        revision=self.context_revision
        await self.close()
        self.session_id=str(uuid4());self.seen.clear();self.sequences.clear()
        while not self.queue.empty(): self.queue.get_nowait()
        await self.connect()
        for filters in self.subscriptions:
            await self.request('ui.context.subscribe',{**filters,'since_context_revision':revision})
        return await self.context(since_context_revision=revision)
    async def events(self):
        while True:
            event=await self.queue.get()
            if self.needs_resync:
                yield {'type':'resync','snapshot':await self.context(since_context_revision=self.context_revision)}
            self.context_revision=max(self.context_revision,event['context_revision'])
            yield event
