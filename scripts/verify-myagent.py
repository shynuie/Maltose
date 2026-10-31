"""Run tests from a temporary working directory, preserving user runtime data."""
import io
import os
from pathlib import Path
import subprocess
import sys
import tarfile
import tempfile
root=Path('/Users/Marvin/Workspace/MyAgent')
mode=sys.argv[1] if len(sys.argv)>1 else 'focused'
with tempfile.TemporaryDirectory(prefix='maltose-myagent-check-') as work:
    work=Path(work)
    source=root
    if mode=='baseline':
        source=work/'baseline';source.mkdir()
        archive=subprocess.run(['git','archive','HEAD','myagent','tests'],cwd=root,check=True,capture_output=True).stdout
        with tarfile.open(fileobj=io.BytesIO(archive)) as tar:tar.extractall(source,filter='data')
    environment={**os.environ,'PYTHONDONTWRITEBYTECODE':'1','PYTHONPATH':str(source)+':'+str(source/'tests'),'UV_OFFLINE':'1','HF_HUB_OFFLINE':'1'}
    modules=['test_agent','test_maltose_ui_integration','test_runtime_events','test_web_agent_integration','test_ui_tools','test_tts_pipeline','test_voice_loop','test_capabilities','test_knowledge_taskbrain']
    if mode=='baseline':modules=['test_agent']
    if mode=='maltose':modules=['test_maltose_ui_integration']
    if mode=='kws':modules=['test_kws_startup','test_listening','test_kws_record','test_voice_loop','test_maltose_ui_integration']
    command=[str(root/'.venv/bin/python'),'-m','unittest']
    if mode=='full':command+=['discover','-s',str(source/'tests')]
    else:command+=modules
    result=subprocess.run(command,cwd=work,env=environment)
    sys.exit(result.returncode)
