import base64
from copy import deepcopy
import json
import os
from pathlib import Path
import subprocess
import sys
import pytest
ROOT=Path(__file__).resolve().parents[2]
sys.path.insert(0,str(ROOT/'packages/bootstrap'))
from maltose_bootstrap.discovery import discover,secure_file
from maltose_bootstrap.installer import verify_artifact,install
from maltose_bootstrap.wire import WireClient

def offer():
    source=ROOT/'apps/macos/MaltoseApp/Resources/toolkit'
    manifest=json.loads((source/'manifest.json').read_text())
    return dict(manifest=manifest,signature=(source/'manifest.sig').read_text().strip(),wheel_base64=base64.b64encode((source/manifest['filename']).read_bytes()).decode())

def test_pinned_signature_and_exact_wheel_digest():
    value=offer();manifest,wheel=verify_artifact(value)
    assert len(wheel)==manifest['size']
    damaged=deepcopy(value);damaged['wheel_base64']=base64.b64encode(wheel+b'changed').decode()
    with pytest.raises(ValueError,match='digest'):verify_artifact(damaged)
    damaged=deepcopy(value);damaged['manifest']['version']='99.0.0'
    with pytest.raises(ValueError,match='signature'):verify_artifact(damaged)
    damaged=deepcopy(value);damaged['signature']=base64.b64encode(b'forged').decode()
    with pytest.raises(ValueError,match='signature'):verify_artifact(damaged)

@pytest.mark.parametrize('field,value',[('filename','../../run.whl'),('entrypoint','arbitrary_code'),('protocol','mup/0.2'),('python_min','2.7'),('size',600001)])
def test_incompatible_or_executable_manifest_rejected(field,value):
    value_offer=offer();value_offer['manifest'][field]=value
    with pytest.raises(ValueError):verify_artifact(value_offer)

def test_invalid_signature_never_invokes_uv(tmp_path,monkeypatch):
    value=offer();value['signature']=base64.b64encode(b'forged').decode()
    with pytest.raises(ValueError):install(value,tmp_path,uv='/must-not-execute')
    assert not list(tmp_path.iterdir())

def test_uv_failure_preserves_previous_environment(tmp_path,monkeypatch):
    old=tmp_path/'previous';old.mkdir();(old/'ready').write_text('keep')
    real_run=subprocess.run;calls=[]
    def run(args,**kwargs):
        if args[0]=='uv-test':
            calls.append((args,kwargs['env']))
            return subprocess.CompletedProcess(args,1,b'',b'simulated failure')
        return real_run(args,**kwargs)
    monkeypatch.setattr(subprocess,'run',run)
    with pytest.raises(RuntimeError,match='isolated'):install(offer(),tmp_path,uv='uv-test')
    assert (old/'ready').read_text()=='keep'
    assert not list(tmp_path.glob('.install-*'))
    assert calls[0][1]['UV_OFFLINE']=='1' and calls[0][1]['UV_PYTHON_DOWNLOADS']=='never'

def test_private_descriptors_and_symlink_rejection(tmp_path):
    directory=tmp_path/'discovery';directory.mkdir(mode=0o700)
    public=directory/'world-readable.json';public.write_text('{}');public.chmod(0o644)
    with pytest.raises(ValueError):secure_file(public)
    private=directory/'private.json';private.write_text('{}');private.chmod(0o600)
    link=directory/'link.json';link.symlink_to(private)
    with pytest.raises(ValueError):secure_file(link)
    assert discover(directory)==[]
    directory.chmod(0o755)
    with pytest.raises(ValueError):discover(directory)

@pytest.mark.parametrize('url',['ws://localhost:8765','ws://192.168.1.1:8765','wss://127.0.0.1:8765','ws://127.0.0.1:8765/?token=secret','ws://user@127.0.0.1:8765'])
def test_bootstrap_cannot_follow_non_loopback_or_credential_urls(url):
    with pytest.raises(ValueError):WireClient(url)
