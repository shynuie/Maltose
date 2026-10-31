"""Install only a pinned publisher-signed prebuilt wheel in a versioned private uv env."""
import base64
import hashlib
import json
import os
import re
import shutil
import subprocess
import tempfile
from pathlib import Path

def canonical(value):return json.dumps(value,sort_keys=True,separators=(',',':'),ensure_ascii=False).encode()
def verify_artifact(offer,public_key=None):
    manifest=offer['manifest']
    required={'package','version','filename','sha256','size','python_min','protocol','entrypoint'}
    if set(manifest)!=required or manifest['package']!='maltose-ui-runtime' or manifest['protocol']!='mup/0.3' or manifest['entrypoint']!='maltose_runtime':raise ValueError('Unsupported toolkit manifest')
    if not re.fullmatch(r'maltose_ui_runtime-[0-9.]+-py3-none-any\.whl',manifest['filename']):raise ValueError('Invalid toolkit filename')
    if manifest['size']>600000 or manifest['python_min']!='3.12':raise ValueError('Incompatible toolkit')
    key=Path(public_key) if public_key else Path(__file__).with_name('publisher.pem')
    with tempfile.TemporaryDirectory() as tmp:
        source=Path(tmp)/'manifest';signature=Path(tmp)/'signature'
        source.write_bytes(canonical(manifest));signature.write_bytes(base64.b64decode(offer['signature'],validate=True))
        result=subprocess.run(['/usr/bin/openssl','dgst','-sha256','-verify',str(key),'-signature',str(signature),str(source)],capture_output=True,timeout=5)
        if result.returncode:raise ValueError('Toolkit publisher signature verification failed')
    if 'wheel_base64' in offer:
        wheel=base64.b64decode(offer['wheel_base64'],validate=True)
        if len(wheel)!=manifest['size'] or hashlib.sha256(wheel).hexdigest()!=manifest['sha256']:raise ValueError('Toolkit digest mismatch')
        return manifest,wheel
    return manifest,None

def install(offer,root,public_key=None,uv='uv'):
    manifest,wheel=verify_artifact(offer,public_key)
    if wheel is None:raise ValueError('Missing toolkit wheel')
    root=Path(root);root.mkdir(parents=True,exist_ok=True,mode=0o700)
    if root.is_symlink():raise ValueError('Runtime root must not be a symlink')
    os.chmod(root,0o700)
    target=root/manifest['sha256']
    python=target/'env/bin/python'
    if python.exists() and (target/'ready.json').exists():
        if json.loads((target/'ready.json').read_text())==manifest:return python
    staging=Path(tempfile.mkdtemp(prefix='.install-',dir=root))
    try:
        archive=staging/manifest['filename'];archive.write_bytes(wheel)
        environment={**os.environ,'UV_CACHE_DIR':str(root/'cache'),'UV_OFFLINE':'1','UV_PYTHON_DOWNLOADS':'never'}
        result=subprocess.run([uv,'venv','--python','3.12',str(staging/'env')],env=environment,capture_output=True,timeout=120)
        if result.returncode:raise RuntimeError('Unable to create isolated uv environment')
        result=subprocess.run([uv,'pip','install','--python',str(staging/'env/bin/python'),'--no-deps','--no-index','--no-build',str(archive)],env=environment,capture_output=True,timeout=120)
        if result.returncode:raise RuntimeError('Unable to install verified UI toolkit')
        result=subprocess.run([str(staging/'env/bin/python'),'-m','maltose_runtime','--self-test'],capture_output=True,timeout=10)
        if result.returncode:raise RuntimeError('UI toolkit health check failed')
        (staging/'ready.json').write_bytes(canonical(manifest))
        # venv executables are invoked by absolute path; no installed scripts/shebangs are used.
        if target.exists():raise RuntimeError('Unhealthy existing toolkit environment; inspect before replacing')
        staging.rename(target)
        return python
    finally:
        if staging.exists():shutil.rmtree(staging)
