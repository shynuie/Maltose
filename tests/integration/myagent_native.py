"""Real native Host → signed wheel → uv sidecar → real MyAgent TaskBrain with a fake model.
No production credentials, microphone, models or document databases are used.
"""
import json
import os
from pathlib import Path
import sys
import time
sys.path.insert(0,'/Users/Marvin/Workspace/MyAgent')
from myagent.agent.brain import TurnContext
from myagent.agent.taskbrain import TaskBrain
from myagent.agent.agent import VoiceAgent
from myagent.agent.config import AgentConfig
from myagent.runtime import EventHub
from myagent.ui import MaltoseBridge
from myagent.voice import TTSRequest

class Model:
    def complete(self,messages,tools):
        context=messages[0]['content']
        assert os.environ.get('MALTOSE_EXPECT_NODE','selected-chart') in context and 'chart.time_range' in context,'Actual selected context was not injected'
        expected=os.environ.get('MALTOSE_EXPECT_VALUE','2026-10-01')
        assert not expected or expected in context,'Actual selected value was not injected'
        assert any(t['function']['name']=='maltose_context' for t in tools),'Dynamic toolkit tools were not registered'
        time.sleep(.25)
        return {'choices':[{'message':{'content':'已讀取選取區間。'}}]}
class Speaker:
    def synthesize(self,request):time.sleep(.15)

hub=EventHub()
bridge=MaltoseBridge(hub,agent_id='agent.myagent-e2e',name='MyAgent isolated integration test',directory=os.environ['MALTOSE_DISCOVERY'],state_root=os.environ['MALTOSE_STATE'])
brain=TaskBrain(Model(),capability_adapters=[bridge],external_ui_context_provider=bridge.context,runtime_publisher=hub.publish)
agent=VoiceAgent(config=AgentConfig(interruptible_tts=False),brain=brain,speaker=Speaker(),event_hub=hub,observe_speech=True)
bridge.attach(agent,brain);bridge.start()
try:
    deadline=time.monotonic()+25
    while bridge.bootstrap.state!='connected' and time.monotonic()<deadline:time.sleep(.1)
    assert bridge.bootstrap.state=='connected',bridge.bootstrap.last_error
    # Fetching this context is an authenticated IPC → native Host query, not a fixture cache.
    result=brain.process('分析我選的這段',TurnContext(user_id='user-001',speaker_status='identified'))
    assert result=='已讀取選取區間。'
    hub.publish('user_message',{'content':'分析我選的這段'})
    hub.publish('assistant_start',{'message_id':'reply-e2e'})
    hub.publish('assistant_delta',{'message_id':'reply-e2e','content':result})
    agent.speaker.synthesize(TTSRequest(text=result))
    bridge.bootstrap.call('maltose_detach',{'surface_id':os.environ.get('MALTOSE_SURFACE','e2e-chart')})
    time.sleep(.6)
    # Native test sends text via Host user-input queue; it must reach existing submit_text.
    value=agent._command_queue.get(timeout=5)
    assert value=='來自原生 UI 的指令',value
    print('Signed toolkit / uv sidecar / MyAgent context / real runtime events / native input passed')
finally:bridge.close()
