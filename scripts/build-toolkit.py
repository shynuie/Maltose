"""Reproducible pure-Python wheel + signed manifest. Private publisher key never enters app or Git."""
import base64
import csv
import hashlib
import io
import json
import os
from pathlib import Path
import shutil
import subprocess
import zipfile
ROOT=Path(__file__).resolve().parents[1]
cache=ROOT/'.cache/toolkit-signing';cache.mkdir(parents=True,exist_ok=True,mode=0o700)
key=cache/'publisher.key'
public=ROOT/'packages/bootstrap/maltose_bootstrap/publisher.pem'
if not key.exists() and not public.exists():
    subprocess.run(['/usr/bin/openssl','ecparam','-genkey','-name','prime256v1','-noout','-out',str(key)],check=True)
    key.chmod(0o600)
if key.exists():
    derived=subprocess.run(['/usr/bin/openssl','ec','-in',str(key),'-pubout'],check=True,capture_output=True).stdout
    if public.exists() and public.read_bytes()!=derived:raise SystemExit('Publisher key differs from pinned bootstrap key; explicit trust migration required.')
    if not public.exists():public.write_bytes(derived)
# A single stdlib transport implementation is packaged into both trust domains.
shutil.copyfile(ROOT/'packages/bootstrap/maltose_bootstrap/wire.py',ROOT/'packages/ui-runtime/maltose_runtime/wire.py')
output=ROOT/'apps/macos/MaltoseApp/Resources/toolkit';output.mkdir(parents=True,exist_ok=True)
filename='maltose_ui_runtime-0.4.0-py3-none-any.whl';archive=output/filename
files={str(p.relative_to(ROOT/'packages/ui-runtime')).replace(os.sep,'/'):p.read_bytes() for p in sorted((ROOT/'packages/ui-runtime/maltose_runtime').glob('*.py'))}
info='maltose_ui_runtime-0.4.0.dist-info'
files[info+'/METADATA']=b'Metadata-Version: 2.3\nName: maltose-ui-runtime\nVersion: 0.4.0\nRequires-Python: >=3.12\n'
files[info+'/WHEEL']=b'Wheel-Version: 1.0\nGenerator: maltose-build-toolkit\nRoot-Is-Purelib: true\nTag: py3-none-any\n'
rows=[]
for name,data in sorted(files.items()):rows.append([name,'sha256='+base64.urlsafe_b64encode(hashlib.sha256(data).digest()).decode().rstrip('='),str(len(data))])
rows.append([info+'/RECORD','','']);record=io.StringIO();csv.writer(record,lineterminator='\n').writerows(rows);files[info+'/RECORD']=record.getvalue().encode()
with zipfile.ZipFile(archive,'w',compression=zipfile.ZIP_DEFLATED) as z:
    for name,data in sorted(files.items()):
        entry=zipfile.ZipInfo(name,date_time=(2026,1,1,0,0,0));entry.compress_type=zipfile.ZIP_DEFLATED;entry.external_attr=0o644<<16;z.writestr(entry,data)
wheel=archive.read_bytes()
manifest=dict(package='maltose-ui-runtime',version='0.4.0',filename=filename,sha256=hashlib.sha256(wheel).hexdigest(),size=len(wheel),python_min='3.12',protocol='mup/0.3',entrypoint='maltose_runtime')
content=json.dumps(manifest,sort_keys=True,separators=(',',':')).encode()
signature=cache/'signature'
if key.exists():
    (output/'manifest.json').write_bytes(content)
    subprocess.run(['/usr/bin/openssl','dgst','-sha256','-sign',str(key),'-out',str(signature),str(output/'manifest.json')],check=True)
    (output/'manifest.sig').write_text(base64.b64encode(signature.read_bytes()).decode()+'\n')
else:
    # Clones can package the unchanged signed artifact without possessing the signing key.
    if (output/'manifest.json').read_bytes()!=content:raise SystemExit('Toolkit changed but publisher private key is unavailable. Restore the signing key or perform an explicit trust migration.')
    signature.write_bytes(base64.b64decode((output/'manifest.sig').read_text(),validate=False))
    result=subprocess.run(['/usr/bin/openssl','dgst','-sha256','-verify',str(public),'-signature',str(signature),str(output/'manifest.json')],capture_output=True)
    if result.returncode:raise SystemExit('Bundled toolkit signature invalid.')
print('Built signed offline UI toolkit',filename,manifest['sha256'])
