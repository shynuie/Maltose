"""Resolve a running app without assuming a fixed port; retain explicit headless support."""
import os
from pathlib import Path
import sys
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'packages/bootstrap'))
from maltose_bootstrap import discover

def endpoint():
    explicit=os.environ.get('MALTOSE_UI_ENDPOINT')
    if explicit:return explicit
    services=discover()
    selected=os.environ.get('MALTOSE_UI_INSTANCE')
    if selected:services=[s for s in services if s['instance_id']==selected]
    if len(services)==1:return services[0]['endpoint']
    if len(services)>1:raise RuntimeError('Multiple UI apps found; set MALTOSE_UI_INSTANCE to the intended instance_id.')
    # Original headless examples remain usable with --port 8765.
    return 'ws://127.0.0.1:8765'
