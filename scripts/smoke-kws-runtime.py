"""Actual configured KWS worker: local model + synthetic silence, no microphone or recordings."""
import os
from pathlib import Path
import sys
import tempfile
import time
root=Path('/Users/Marvin/Workspace/MyAgent')
sys.path.insert(0,str(root))
from myagent.voice.wake import create_wake_word_detector,load_wake_word_config
with tempfile.TemporaryDirectory(prefix='myagent-kws-smoke-') as temp:
    os.environ['MYAGENT_KWS_LOG']=str(Path(temp)/'kws.log')
    os.environ['HF_HUB_OFFLINE']='1';os.environ['MODELSCOPE_OFFLINE']='1'
    os.chdir(temp)
    started=time.monotonic()
    config=load_wake_word_config(root/'wake.toml')
    detector=create_wake_word_detector(config)
    try:
        print('Configured model worker READY in',round(time.monotonic()-started,2),'seconds',flush=True)
        print('Health before:',detector.health(),flush=True)
        hit=detector.process_frame(b'\0'*32000,16000)
        assert hit is None,'Silence unexpectedly triggered wake'
        detector.reset()
        print('Health after one second synthetic PCM/reset:',detector.health(),flush=True)
    finally:detector.close()
    print('READY/health/PCM/reset/shutdown passed; microphone and private recordings not used')
