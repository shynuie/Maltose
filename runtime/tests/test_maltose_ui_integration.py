from __future__ import annotations
import unittest
from maltose.agent.brain import TurnContext
from maltose.agent.taskbrain import TaskBrain,ToolRegistry
from maltose.runtime import EventHub
from maltose.ui import MaltoseBridge

class FakeBootstrap:
    def __init__(self,**kwargs):self.kwargs=kwargs;self.events=[];self.calls=[]
    def start(self):pass
    def connect(self,*_):return {'state':'connected'}
    def runtime(self,event,data):self.events.append((event,data));return {}
    def context(self):return {'context_revision':2,'fresh':True,'focused_node_id':'chart-selected','surfaces':[{'selection':{'node_id':'chart-selected','kind':'chart.time_range','value':{'start':1,'end':2}}}]}
    def call(self,name,arguments):self.calls.append((name,arguments));return {'ok':True}
    def close(self):pass
class FakeModel:
    def __init__(self):self.messages=None
    def complete(self,messages,tools):self.messages=messages;return {'choices':[{'message':{'content':'已讀取選取區間。'}}]}

class MaltoseIntegrationTests(unittest.TestCase):
    def test_ui_canvas_block_becomes_bounded_typed_surface(self):
        bridge=MaltoseBridge(EventHub(),bootstrap_factory=FakeBootstrap)
        bridge._present({'block_type':'ui_canvas','block_id':'random_doodle','scene_id':'random_doodle','title':'隨手畫的小房子','elements':[
            {'type':'node','id':'house','x':180,'y':150,'width':220,'height':170,'label':'小房子','color':'#F4B183'},
            {'type':'node','id':'roof','x':160,'y':70,'width':260,'height':100,'label':'屋頂','color':'#C0504D'},
            {'type':'node','id':'door','x':260,'y':235,'width':60,'height':85,'label':'門','color':'#8064A2'},
            {'type':'node','id':'sun','x':520,'y':70,'width':90,'height':90,'label':'太陽','color':'#FFD966'},
            {'type':'node','id':'tree','x':30,'y':190,'width':100,'height':170,'label':'樹','color':'#70AD47'},
            {'type':'text','id':'caption','x':190,'y':370,'label':'<script>一般文字</script>'},
            {'type':'node','id':'bad-color','x':0,'y':0,'width':20,'height':20,'color':'url(javascript:alert(1))'},
            {'type':'unknown','id':'ignored'}]})
        name,args=bridge.bootstrap.calls[0]
        self.assertEqual(name,'maltose_show')
        self.assertEqual(args['surface_id'],'myagent-random_doodle')
        root=args['document']['root']
        self.assertEqual(root['type'],'canvas')
        self.assertEqual(root['props'],{'width':640,'height':480})
        self.assertEqual([node['node_id'] for node in root['children']],['house','roof','door','sun','tree','caption','bad-color'])
        self.assertEqual(root['children'][0]['type'],'canvas.rect')
        self.assertEqual(root['children'][5]['type'],'canvas.text')
        self.assertEqual(root['children'][5]['props']['label'],'<script>一般文字</script>')
        self.assertEqual(root['children'][6]['props']['color'],'#E5E7EB')
    def test_verified_turn_receives_fresh_context_and_model_events(self):
        hub=EventHub();model=FakeModel()
        bridge=MaltoseBridge(hub,bootstrap_factory=FakeBootstrap)
        brain=TaskBrain(model,capability_adapters=[bridge],external_ui_context_provider=bridge.context,runtime_publisher=hub.publish)
        bridge.attach(None,brain)
        subscription=hub.subscribe()
        result=brain.process('分析我選的這段',TurnContext(user_id='user-001',speaker_status='identified'))
        self.assertEqual(result,'已讀取選取區間。')
        self.assertIn('chart-selected',model.messages[0]['content'])
        self.assertIn('untrusted data',model.messages[0]['content'])
        self.assertEqual(next(subscription).type,'model_started')
        self.assertEqual(next(subscription).type,'model_finished');subscription.close()
    def test_unverified_speaker_cannot_read_native_ui_context(self):
        hub=EventHub();model=FakeModel();bridge=MaltoseBridge(hub,bootstrap_factory=FakeBootstrap)
        brain=TaskBrain(model,external_ui_context_provider=bridge.context);bridge.attach(None,brain)
        brain.process('分析這張圖',TurnContext(user_id='unknown',speaker_status='unknown'))
        self.assertNotIn('chart-selected',model.messages[0]['content'])
        bridge._tools_ready([{'name':'maltose_context','description':'Read UI','parameters':{'type':'object'}}])
        self.assertEqual(brain.tools.execute('maltose_context',{})['error'],'speaker_verification_required')
    def test_tool_events_are_automatic_and_do_not_contain_arguments(self):
        registry=ToolRegistry();events=[];registry.event_publisher=lambda kind,data:events.append((kind,data))
        registry.register('sample','sample',{'type':'object'},lambda args:args['secret'])
        self.assertEqual(registry.execute('sample',{'secret':'not-telemetry'}),'not-telemetry')
        self.assertEqual(events,[('tool_started',{'tool':'sample'}),('tool_finished',{'tool':'sample'})])
    def test_native_text_input_uses_existing_agent_queue(self):
        bridge=MaltoseBridge(EventHub(),bootstrap_factory=FakeBootstrap)
        class Agent:
            def submit_text(self,text):self.text=text
        agent=Agent();bridge.attach(agent)
        bridge._notification({'notification':'input','value':{'kind':'text','text':'請分析資料'}})
        self.assertEqual(agent.text,'請分析資料')
    def test_existing_web_switch_is_not_required_for_state_forwarding(self):
        bridge=MaltoseBridge(EventHub(),bootstrap_factory=FakeBootstrap)
        bridge._forward('state_changed',{'state':'thinking'})
        bridge._forward('assistant_delta',{'message_id':'reply','content':'正在回答','secret':'excluded'})
        self.assertEqual(bridge.bootstrap.events,[('state_changed',{'state':'thinking'}),('assistant_delta',{'message_id':'reply','content':'正在回答'})])
    def test_cli_config_enables_native_bridge_without_web(self):
        from maltose.agent.cli import build_parser
        from maltose.agent.config import load_cli_defaults
        from pathlib import Path
        import tempfile
        with tempfile.TemporaryDirectory() as temp:
            config=Path(temp)/'agent.toml';config.write_text('[maltose]\nenabled=true\nagent_id="agent.test"\nname="Test"\n')
            parser=build_parser();parser.set_defaults(**load_cli_defaults(config));args=parser.parse_args([])
            self.assertTrue(args.maltose);self.assertFalse(args.web);self.assertEqual(args.maltose_agent_id,'agent.test')
    def test_model_and_tool_failure_close_actual_runtime_state(self):
        events=[]
        class BrokenModel:
            def complete(self,*args):raise RuntimeError('model unavailable')
        brain=TaskBrain(BrokenModel(),runtime_publisher=lambda kind,data:events.append((kind,data)))
        with self.assertRaises(RuntimeError):brain.process('test')
        self.assertEqual(events,[('model_started',{}),('model_failed',{})])
        registry=ToolRegistry();registry.event_publisher=lambda kind,data:events.append((kind,data))
        def broken(_):raise RuntimeError('private diagnostic')
        registry.register('broken','test',{'type':'object'},broken)
        with self.assertRaises(RuntimeError):registry.execute('broken',{'secret':'not-telemetry'})
        self.assertEqual(events[-2:],[('tool_started',{'tool':'broken'}),('tool_failed',{'tool':'broken'})])
    def test_ui_tool_failure_returns_to_model_without_crashing_agent(self):
        class FailingBootstrap(FakeBootstrap):
            def call(self,name,arguments):raise RuntimeError('private transport detail')
        bridge=MaltoseBridge(EventHub(),bootstrap_factory=FailingBootstrap)
        brain=TaskBrain(FakeModel(),capability_adapters=[bridge]);bridge.attach(None,brain)
        bridge._tools_ready([{'name':'maltose_show','description':'Show UI','parameters':{'type':'object'}}])
        result=brain.tools.execute('maltose_show',{})
        self.assertEqual(result['error'],'ui_tool_failed')
        self.assertNotIn('private transport detail',str(result))

    def test_mup_tool_failure_exposes_only_host_error_code_and_reason(self):
        class HostFailure(RuntimeError):code='invalid_document'
        class FailingBootstrap(FakeBootstrap):
            def call(self,name,arguments):raise HostFailure('Document does not conform to the supported UI schema')
        bridge=MaltoseBridge(EventHub(),bootstrap_factory=FailingBootstrap)
        brain=TaskBrain(FakeModel(),capability_adapters=[bridge]);bridge.attach(None,brain)
        bridge._tools_ready([{'name':'maltose_show','description':'Show UI','parameters':{'type':'object'}}])
        result=brain.tools.execute('maltose_show',{})
        self.assertEqual(result['code'],'invalid_document')
        self.assertIn('supported UI schema',result['reason'])

    def test_unknown_ui_action_cannot_execute_commands_or_approve(self):
        bridge=MaltoseBridge(EventHub(),bootstrap_factory=FakeBootstrap)
        class Agent:
            def __init__(self):self.inputs=[]
            def submit_text(self,text):self.inputs.append(text)
        agent=Agent();bridge.attach(agent)
        bridge._notification({'notification':'action','value':{'changes':{'action_id':'shell.exec','command':'must not run'}}})
        self.assertEqual(agent.inputs,[]);self.assertEqual(bridge.bootstrap.calls,[])
if __name__=='__main__':unittest.main()
