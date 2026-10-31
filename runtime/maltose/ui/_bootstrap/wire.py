"""Bounded, synchronous RFC6455 text client for the stdlib-only local bootstrap.
One request is in flight at a time. Control frames and fragmented server messages
are handled; browser origins, redirects, arbitrary hosts and compression are not used.
"""
import base64
import hashlib
import json
import os
import socket
import struct
import threading
import uuid
from urllib.parse import urlparse

MAX_MESSAGE=1_048_576
class MUPFailure(Exception):
    def __init__(self,error):
        self.code=error.get('code','unknown');super().__init__(error.get('message','MUP failed'))

class WireClient:
    def __init__(self,endpoint,timeout=5):
        url=urlparse(endpoint)
        if url.scheme!='ws' or url.hostname!='127.0.0.1' or not url.port or url.path not in ('','/') or url.query or url.fragment or url.username:
            raise ValueError('Only direct IPv4 loopback WebSocket endpoints are allowed')
        self.socket=socket.create_connection(('127.0.0.1',url.port),timeout=timeout)
        self.socket.settimeout(timeout);self.buffer=bytearray();self.lock=threading.RLock()
        self.session_id=str(uuid.uuid4());self.events=[]
        key=base64.b64encode(os.urandom(16)).decode()
        request=f'GET / HTTP/1.1\r\nHost: 127.0.0.1:{url.port}\r\nUpgrade: websocket\r\nConnection: Upgrade\r\nSec-WebSocket-Version: 13\r\nSec-WebSocket-Key: {key}\r\n\r\n'
        self.socket.sendall(request.encode('ascii'))
        while b'\r\n\r\n' not in self.buffer:
            if len(self.buffer)>16384:self.close();raise ValueError('Oversized handshake')
            self.buffer.extend(self._read_socket())
        raw,remaining=bytes(self.buffer).split(b'\r\n\r\n',1);self.buffer=bytearray(remaining)
        lines=raw.decode('ascii').split('\r\n')
        headers={line.split(':',1)[0].lower():line.split(':',1)[1].strip() for line in lines[1:] if ':' in line}
        expected=base64.b64encode(hashlib.sha1((key+'258EAFA5-E914-47DA-95CA-C5AB0DC85B11').encode()).digest()).decode()
        if lines[0].split()[1]!='101' or headers.get('sec-websocket-accept','').strip()!=expected:
            self.close();raise ValueError('Invalid WebSocket upgrade')
    def _read_socket(self):
        data=self.socket.recv(65536)
        if not data:raise ConnectionError('UI connection closed')
        return data
    def _read(self,n):
        while len(self.buffer)<n:self.buffer.extend(self._read_socket())
        data=bytes(self.buffer[:n]);del self.buffer[:n];return data
    def _send_frame(self,opcode,payload):
        if len(payload)>MAX_MESSAGE:raise ValueError('Oversized message')
        length=len(payload);mask=os.urandom(4)
        header=bytes([0x80|opcode])
        if length<126:header+=bytes([0x80|length])
        elif length<65536:header+=bytes([0x80|126])+struct.pack('!H',length)
        else:header+=bytes([0x80|127])+struct.pack('!Q',length)
        self.socket.sendall(header+mask+bytes(b^mask[i%4] for i,b in enumerate(payload)))
    def _receive(self):
        chunks=bytearray();started=False
        while True:
            a,b=self._read(2);final=bool(a&0x80);op=a&15;length=b&127
            if a&0x70 or b&0x80:raise ValueError('Invalid server frame')
            if length==126:length=struct.unpack('!H',self._read(2))[0]
            elif length==127:length=struct.unpack('!Q',self._read(8))[0]
            if length>MAX_MESSAGE or len(chunks)+length>MAX_MESSAGE:raise ValueError('Oversized frame')
            if op>=8 and (not final or length>125):raise ValueError('Invalid control frame')
            payload=self._read(length)
            if op==8:raise ConnectionError('UI closed connection')
            if op==9:self._send_frame(10,payload);continue
            if op==10:continue
            if op==1 and not started:started=True
            elif op!=0 or not started:raise ValueError('Expected text message')
            chunks.extend(payload)
            if final:return json.loads(chunks.decode('utf8'))
    def request(self,name,payload=None):
        with self.lock:
            rid=str(uuid.uuid4())
            message=dict(protocol='mup/0.3',message_id=str(uuid.uuid4()),session_id=self.session_id,request_id=rid,type='command',name=name,payload=payload or {})
            self._send_frame(1,json.dumps(message,separators=(',',':'),ensure_ascii=False).encode())
            for _ in range(256):
                reply=self._receive()
                if reply.get('protocol')!='mup/0.3':raise ValueError('Protocol mismatch')
                if reply.get('type')=='event':
                    self.events.append(reply)
                    if len(self.events)>128:self.events=self.events[-128:]
                    continue
                if reply.get('request_id')!=rid:raise ValueError('Request correlation mismatch')
                if not reply.get('ok'):raise MUPFailure(reply['error'])
                return reply['result']
            raise ValueError('Event flood before response')
    def authenticate(self,token):
        result=self.request('host.authenticate',{'token':token});self.session_id=result['session_id'];return result
    def close(self):
        try:self.socket.close()
        except OSError:pass
