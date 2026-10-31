"""Maintain the MUP source-of-truth schemas (no external generator dependency)."""
import json
from pathlib import Path
ROOT = Path(__file__).resolve().parents[1]
def obj(props=None, required=None):
    props = props or {}
    return dict(type='object', properties=props, required=list(props) if required is None else required, additionalProperties=False)
def arr(item, maximum=256): return dict(type='array', items=item, maxItems=maximum)
def enum(*values): return {'enum':list(values)}
def ref(name): return {'$ref':'#/$defs/'+name}
def nullable(s): return {'anyOf':[s,{'type':'null'}]}
string = {'type':'string','minLength':1,'maxLength':256}
text = {'type':'string','maxLength':16384}
identifier = {'type':'string','pattern':r'^[A-Za-z0-9][A-Za-z0-9._-]{0,127}$','maxLength':128,'minLength':1}
uuid = {'type':'string','format':'uuid'}
number = {'type':'number'}
nat = {'type':'integer','minimum':0,'maximum':9007199254740991}
bool_ = {'type':'boolean'}
color = {'type':'string','pattern':r'^#[0-9A-Fa-f]{6}$'}
value = {'anyOf':[{'type':'null'},bool_,number,{'type':'string','maxLength':4096}]}
defs = {'id':identifier,'uuid':uuid}
defs['props'] = obj({'text':text,'title':text,'label':text,'action_id':identifier,'columns':arr(string,32),'rows':arr(arr(value,32),1000),'points':arr(dict(type='array',items={'anyOf':[number,string]},minItems=2,maxItems=2),10000),'data_id':identifier,'sensitive':bool_,'x':{'type':'number','minimum':0,'maximum':4096},'y':{'type':'number','minimum':0,'maximum':4096},'width':{'type':'number','minimum':1,'maximum':4096},'height':{'type':'number','minimum':1,'maximum':4096},'color':color,'background_color':color}, [])
defs['node'] = obj({'node_id':identifier,'type':enum('stack','text','button','table','chart.line','canvas','canvas.rect','canvas.ellipse','canvas.triangle','canvas.text'),'props':ref('props'),'children':arr(ref('node'),256)},['node_id','type','props'])
defs['document'] = obj({'root':ref('node'),'actions':arr(identifier,128)},['root'])
defs['placement'] = obj({'x':number,'y':number,'width':{'type':'number','minimum':240,'maximum':10000},'height':{'type':'number','minimum':180,'maximum':10000},'screen_id':identifier},[])
defs['patch'] = {'oneOf':[
 obj({'op':{'const':'set_props'},'node_id':identifier,'props':ref('props')}),
 obj({'op':{'const':'insert_node'},'parent_id':identifier,'index':nat,'node':ref('node')}),
 obj({'op':{'const':'remove_node'},'node_id':identifier}),
 obj({'op':{'const':'move_node'},'node_id':identifier,'parent_id':identifier,'index':nat})]}
fields = enum('focus','selection','viewport','layout','visible_nodes','interaction')
events = ['context.focus_changed','context.selection_changed','context.viewport_changed','context.surface_visibility_changed','context.surface_moved','context.surface_detached','context.surface_attached','context.user_override_changed','context.stale','context.permission_changed']
defs['context_event_kind'] = enum(*events)
defs['selection'] = obj({'node_id':identifier,'kind':enum('chart.time_range','node'),'value':obj({'start':value,'end':value},[])},['node_id','kind'])
defs['viewport'] = obj({'node_id':identifier,'x_domain':dict(type='array',items={'anyOf':[number,string]},minItems=2,maxItems=2)},['node_id','x_domain'])
sid = {'surface_id':identifier}
commands = {
 'host.discover':obj(),
 'host.pair.request':obj({'name':string,'agent_id':identifier,'claim':{'type':'string','minLength':32,'maxLength':256}}),
 'host.pair.poll':obj({'pairing_id':uuid,'claim':{'type':'string','minLength':32,'maxLength':256}}),
 'host.toolkit.get':obj(),
 'agent.runtime.publish':obj({'run_id':uuid,'sequence':nat,'event':enum('heartbeat','state_changed','model_started','model_finished','model_failed','tool_started','tool_finished','tool_failed','speech_started','speech_finished','assistant_start','assistant_delta','assistant_end','user_message','task_progress','error'),'data':obj({'state':enum('initializing','standby','listening','thinking','speaking','shutdown','error'),'message_id':identifier,'content':text,'tool':string,'detail':text,'progress':{'type':'number','minimum':0,'maximum':1}},[])}),
 'agent.input.poll':obj(),
 'host.authenticate':obj({'token':{'type':'string','minLength':32,'maxLength':256}}),
 'host.capabilities':obj(),
 'surface.create':obj({'surface_id':identifier,'kind':enum('workspace','window','overlay'),'title':string,'document':ref('document'),'placement':ref('placement')},['surface_id','title','document']),
 'surface.list':obj(),
 'surface.get':obj(sid),
 'surface.set_visibility':obj({**sid,'visible':bool_}),
 'surface.close':obj(sid), 'surface.detach':obj(sid), 'surface.attach':obj(sid),
 'ui.render':obj({**sid,'expected_revision':nat,'document':ref('document')}),
 'ui.patch':obj({**sid,'expected_revision':nat,'operations':dict(type='array',items=ref('patch'),minItems=1,maxItems=128)}),
 'ui.inspect':obj(sid),
 'events.subscribe':obj({'surface_id':identifier,'kinds':arr(enum('ui.action','data.updated',*events),16)},[]),
 'events.unsubscribe':obj({'subscription_id':uuid}),
 'data.register':obj({'data_id':identifier}),
 'data.publish':obj({'data_id':identifier,'sequence':nat,'points':arr(dict(type='array',items={'anyOf':[number,string]},minItems=2,maxItems=2),10000)}),
 'data.unregister':obj({'data_id':identifier}),
 'ui.context.get':obj({'surface_id':identifier,'include':arr(fields,6),'max_age_ms':nat,'since_context_revision':nat},[]),
 'ui.context.subscribe':obj({'surface_id':identifier,'kinds':arr(ref('context_event_kind'),10),'since_context_revision':nat},[]),
 'ui.context.unsubscribe':obj({'subscription_id':uuid}),
 'ui.context.resolve_reference':obj({'phrase':{'type':'string','minLength':1,'maxLength':256},'surface_id':identifier,'node_id':identifier,'max_age_ms':nat},['phrase'])
}
# Runtime fields are event-specific; a status event cannot smuggle another agent identity.
runtime_data=commands['agent.runtime.publish']['properties']['data']['properties']
runtime_fields={
 'heartbeat':[], 'state_changed':['state'],
 'model_started':[], 'model_finished':[], 'model_failed':[],
 'tool_started':['tool'], 'tool_finished':['tool'], 'tool_failed':['tool'],
 'speech_started':[], 'speech_finished':[],
 'assistant_start':['message_id'], 'assistant_delta':['message_id','content'],
 'assistant_end':['message_id','content'], 'user_message':['content'],
 'task_progress':['detail','progress'], 'error':['detail']
}
commands['agent.runtime.publish']['oneOf']=[
 {'properties':{'event':{'const':event},'data':obj({field:runtime_data[field] for field in fields},
   ['message_id'] if event=='assistant_end' else [] if event=='task_progress' else fields)}}
 for event,fields in runtime_fields.items()
]
envelope = obj({'protocol':{'const':'mup/0.3'},'message_id':uuid,'session_id':uuid,'request_id':uuid,'idempotency_key':uuid,'type':{'const':'command'},'name':enum(*commands),'payload':{'type':'object'}}, ['protocol','message_id','session_id','request_id','type','name','payload'])
envelope['allOf']=[{'if':{'properties':{'name':{'const':name}}},'then':{'properties':{'payload':payload}}} for name,payload in commands.items()]
base={'$schema':'https://json-schema.org/draft/2020-12/schema','$defs':defs}
context = obj({'context_revision':nat,'captured_at':{'type':'string','format':'date-time'},'active_app':nullable(string),'focused_surface_id':nullable(identifier),'focused_node_id':nullable(identifier),'private_focus':bool_,'fresh':bool_,'resync_required':bool_,'unchanged':bool_,'surfaces':arr(obj({'surface_id':identifier,'owner_agent_id':identifier,'kind':enum('workspace','window','overlay'),'visible':bool_,'title':string,'selected_node_ids':arr(identifier),'selection':nullable(ref('selection')),'viewport':nullable(ref('viewport')),'layout':ref('placement'),'visible_nodes':arr(identifier),'interaction':nullable(obj({'node_id':identifier,'at':string})),'document_revision':nat,'context_revision':nat,'redacted':bool_,'captured_at':string,'stale':bool_,'data_stale':bool_},['surface_id','owner_agent_id','kind','visible','title','document_revision','context_revision','redacted','captured_at','stale']))},['context_revision','captured_at','active_app','focused_surface_id','focused_node_id','private_focus','fresh','resync_required','surfaces'])
bridge = obj({'surface_id':identifier,'document_revision':nat,'sequence':nat,'kind':enum('focus_changed','selection_changed','viewport_changed','action'),'node_id':identifier,'selection':nullable(ref('selection')),'viewport':ref('viewport'),'action_id':identifier},['surface_id','document_revision','sequence','kind','node_id'])
bridge['allOf']=[{'if':{'properties':{'kind':{'const':k}}},'then':{'required':[f]}} for k,f in [('selection_changed','selection'),('viewport_changed','viewport'),('action','action_id')]]
response=obj({'protocol':{'const':'mup/0.3'},'request_id':uuid,'ok':bool_,'result':{},'error':obj({'code':string,'message':string,'details':{'type':'object'}})},['protocol','request_id','ok'])
response['oneOf']=[{'properties':{'ok':{'const':True}},'required':['result'],'not':{'required':['error']}},{'properties':{'ok':{'const':False}},'required':['error'],'not':{'required':['result']}}]
event=obj({'protocol':{'const':'mup/0.3'},'type':{'const':'event'},'event_id':uuid,'subscription_id':uuid,'source_agent_id':identifier,'surface_id':nullable(identifier),'sequence':nat,'timestamp':{'type':'string','format':'date-time'},'name':enum(*events,'ui.action','data.updated'),'context_revision':nat,'changes':{'type':'object'}},None)
surface_model=obj({'surface_id':identifier,'owner_agent_id':identifier,'kind':enum('workspace','window','overlay'),'revision':nat,'title':string,'document':ref('document'),'placement':ref('placement'),'visibility':bool_,'lifecycle':enum('active','closed'),'created_at':{'type':'string','format':'date-time'},'updated_at':{'type':'string','format':'date-time'},'user_overrides':obj({'viewport':ref('viewport'),'window_placement':ref('placement')},[])})
for name, schema in [('surface',surface_model),('command',envelope),('context',context),('bridge',bridge),('response',response),('event',event),('document',ref('document'))]:
    schema={**base,'$id':f'https://maltose.local/mup/0.3/{name}.schema.json',**schema}
    content=json.dumps(schema,indent=2,ensure_ascii=False)+'\n'
    for folder in [ROOT/'packages/mup-protocol',ROOT/'native/Protocol/Schemas',ROOT/'packages/sdk-python/maltose/schemas']:
        folder.mkdir(parents=True,exist_ok=True)
        (folder/f'{name}.schema.json').write_text(content)
# Golden corpus: common to Swift, TS and Python.
def command(name,payload): return dict(protocol='mup/0.3',message_id='00000000-0000-4000-8000-000000000001',session_id='00000000-0000-4000-8000-000000000002',request_id='00000000-0000-4000-8000-000000000003',type='command',name=name,payload=payload)
node=dict(node_id='chart-1',type='chart.line',props={'title':'Synthetic prices','points':[[1,10],[2,12]]})
canvas=dict(node_id='scene',type='canvas',props={'width':640,'height':480},children=[dict(node_id='house',type='canvas.rect',props={'x':180,'y':150,'width':220,'height':170,'color':'#F4B183','label':'小房子'})])
valid=[command('host.capabilities',{}),command('surface.create',{'surface_id':'market-1','title':'Market Monitor','document':{'root':node}}),command('ui.context.get',{'include':['focus','selection','viewport']}),command('surface.create',{'surface_id':'scene-1','title':'Canvas Scene','document':{'root':canvas}})]
invalid=[{**valid[0],'protocol':'mup/0.2'},{**valid[0],'owner_agent_id':'forged'},command('surface.get',{'surface_id':2}),command('ui.patch',{'surface_id':'market-1','expected_revision':0,'operations':[{'op':'eval','code':'alert(1)'}]}),command('surface.create',{'surface_id':'s','title':'X','document':{'root':{**node,'type':'javascript'}}}),command('ui.context.get',{'max_age_ms':-1}),{**valid[0],'request_id':'bad'},command('surface.create',{'surface_id':'scene-2','title':'Bad color','document':{'root':dict(node_id='scene',type='canvas',props={'width':640,'height':480},children=[dict(node_id='shape',type='canvas.rect',props={'x':0,'y':0,'width':20,'height':20,'color':'red'})])}})]
runtime={'run_id':'00000000-0000-4000-8000-000000000004','sequence':1,'event':'state_changed','data':{'state':'thinking'}}
valid += [command('host.discover',{}),command('host.pair.request',{'name':'MyAgent','agent_id':'agent.myagent','claim':'x'*40}),command('agent.runtime.publish',runtime),command('agent.input.poll',{})]
invalid += [command('agent.runtime.publish',{**runtime,'agent_id':'agent.other'}),command('agent.runtime.publish',{**runtime,'data':{}}),command('agent.runtime.publish',{**runtime,'event':'assistant_delta','data':{'message_id':'reply'}}),command('host.pair.request',{'name':'Fake','agent_id':'agent.fake','claim':'short'})]
for name,items in [('valid',valid),('invalid',invalid)]:
    (ROOT/f'packages/mup-protocol/fixtures/{name}.json').write_text(json.dumps(items,indent=2)+'\n')
