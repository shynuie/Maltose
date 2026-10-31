"""Isolated live-host restart/revocation exercise. Never accepts a production pairing."""
import os
from pathlib import Path
import sys
import time
sys.path.insert(0,str(Path(__file__).resolve().parents[2]/'packages/bootstrap'))
from maltose_bootstrap import Bootstrap
root=Path(os.environ['MALTOSE_STATE'])
connected=0
def status(value):
    global connected
    if value['state']=='connected':
        connected+=1;(root/f'connected-{connected}').touch()
bridge=Bootstrap(agent_id='agent.reconnect',name='Isolated restart test',directory=os.environ['MALTOSE_DISCOVERY'],state_root=root,on_status=status)
bridge.start()
try:
    deadline=time.monotonic()+30
    while time.monotonic()<deadline:
        if connected>=2 and bridge.state=='authorization_required':
            assert bridge.worker.closed
            print('Dynamic-port restart reconnected without pairing; revoked credentials stopped reconnect')
            break
        time.sleep(.1)
    else:raise AssertionError(f'Incomplete recovery: {connected} / {bridge.state} / {bridge.last_error}')
finally:bridge.close()
