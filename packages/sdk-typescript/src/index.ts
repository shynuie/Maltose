import {Ajv2020} from 'ajv/dist/2020.js';
import formats from 'ajv-formats';
import type {FormatsPlugin} from 'ajv-formats';
import { commandSchema,responseSchema,eventSchema,contextSchema,surfaceSchema } from './schemas.js';
export const protocol = 'mup/0.3' as const;
const ajv=new Ajv2020({strict:false});(formats as unknown as FormatsPlugin)(ajv);
const validators={command:ajv.compile(commandSchema),response:ajv.compile(responseSchema),event:ajv.compile(eventSchema),context:ajv.compile(contextSchema),surface:ajv.compile(surfaceSchema)};
export function validate(value:unknown,name:keyof typeof validators='command'):void {
 if(!validators[name](value))throw new Error('Invalid MUP '+name);
}
export type MUPResponse={protocol:string;request_id:string;ok:boolean;result?:unknown;error?:{code:string;message:string;details:Record<string,unknown>}};
export class Client {
 private socket?:WebSocket;private session=crypto.randomUUID();private pending=new Map<string,{resolve:(v:unknown)=>void;reject:(e:Error)=>void;timer:ReturnType<typeof setTimeout>}>();
 private seen=new Set<string>();private sequences=new Map<string,number>();private subscriptions:Record<string,unknown>[]=[];
 contextRevision=0;needsResync=true;onEvent?:(event:Record<string,unknown>)=>void;
 constructor(private token:string,private url='ws://127.0.0.1:8765') {const u=new URL(url);if(u.protocol!=='ws:'||u.hostname!=='127.0.0.1')throw new Error('Loopback required');}
 async connect(){
  const ws=new WebSocket(this.url);this.socket=ws;
  await new Promise<void>((resolve,reject)=>{const timer=setTimeout(()=>{ws.close();reject(new Error('Connection timeout'));},5000);ws.onopen=()=>{clearTimeout(timer);resolve();};ws.onerror=()=>{clearTimeout(timer);reject(new Error('Connection failed'));};});
  ws.onmessage=event=>{if(this.socket!==ws)return;try{
   const msg=JSON.parse(String(event.data));
   if(msg.type==='event'){
    validate(msg,'event');if(this.seen.has(msg.event_id))return;if(this.seen.size>=2048)this.seen.clear();this.seen.add(msg.event_id);
    const old=this.sequences.get(msg.subscription_id)??0;if(msg.sequence<=old)return;if(msg.sequence!==old+1)this.needsResync=true;this.sequences.set(msg.subscription_id,msg.sequence);
    if(['context.stale','context.permission_changed'].includes(msg.name))this.needsResync=true;
    this.contextRevision=Math.max(this.contextRevision,msg.context_revision);this.onEvent?.(msg);
   }else{validate(msg,'response');const p=this.pending.get(msg.request_id);if(p){clearTimeout(p.timer);this.pending.delete(msg.request_id);msg.ok?p.resolve(msg.result):p.reject(Object.assign(new Error(msg.error.message),{code:msg.error.code}));}}
  }catch{this.needsResync=true;ws.close();}};
  ws.onclose=()=>{if(this.socket!==ws)return;this.needsResync=true;for(const p of this.pending.values()){clearTimeout(p.timer);p.reject(new Error('Disconnected'));}this.pending.clear();};
  const result=await this.request('host.authenticate',{token:this.token}) as {session_id:`${string}-${string}-${string}-${string}-${string}`};this.session=result.session_id;return this;
 }
 request(name:string,payload:Record<string,unknown>={},options:{idempotencyKey?:string;requestID?:string}={}):Promise<unknown>{
  const msg={protocol,message_id:crypto.randomUUID(),session_id:this.session,request_id:options.requestID??crypto.randomUUID(),type:'command',name,payload,...(options.idempotencyKey?{idempotency_key:options.idempotencyKey}:{})};validate(msg);
  if(!this.socket||this.socket.readyState!==WebSocket.OPEN)return Promise.reject(new Error('Not connected'));
  if(this.pending.has(msg.request_id))return Promise.reject(new Error('Duplicate in-flight request'));
  return new Promise((resolve,reject)=>{const timer=setTimeout(()=>{this.pending.delete(msg.request_id);reject(new Error('Request timeout'));},10000);this.pending.set(msg.request_id,{resolve,reject,timer});this.socket!.send(JSON.stringify(msg));});
 }
 async context(filters:Record<string,unknown>={}){const snapshot=await this.request('ui.context.get',filters) as Record<string,unknown>;validate(snapshot,'context');this.contextRevision=snapshot.context_revision as number;this.needsResync=false;return snapshot;}
 async subscribeContext(filters:Record<string,unknown>={}){const result=await this.request('ui.context.subscribe',{...filters,since_context_revision:this.contextRevision});this.subscriptions.push({...filters});return result;}
 async reconnect(){const revision=this.contextRevision;this.close();this.session=crypto.randomUUID();this.seen.clear();this.sequences.clear();await this.connect();for(const f of this.subscriptions)await this.request('ui.context.subscribe',{...f,since_context_revision:revision});return this.context({since_context_revision:revision});}
 close(){const old=this.socket;this.socket=undefined;old?.close();this.needsResync=true;for(const p of this.pending.values()){clearTimeout(p.timer);p.reject(new Error("Disconnected"));}this.pending.clear();}
}
