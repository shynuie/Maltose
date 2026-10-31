"""Apply the enumerated KWS repair only, with concurrent-edit protection."""
from pathlib import Path
import hashlib,json,os,shutil
root=Path(__file__).resolve().parents[1];stage=root/'.cache/kws-startup/edit';target=Path('/Users/Marvin/Workspace/MyAgent')
entries=json.loads((stage/'apply-manifest.json').read_text())
for entry in entries:
    name=entry['path'];assert '..' not in Path(name).parts and not Path(name).is_absolute()
    source=stage/name;dest=target/name
    if dest.exists():
        current=hashlib.sha256(dest.read_bytes()).hexdigest()
        assert current in (entry['original'],hashlib.sha256(source.read_bytes()).hexdigest()),'Concurrent edit: '+name
    else:assert entry['original'] is None,name
for entry in entries:
    dest=target/entry['path'];source=stage/entry['path'];dest.parent.mkdir(parents=True,exist_ok=True)
    temp=dest.with_name(dest.name+'.kws-tmp');temp.write_bytes(source.read_bytes())
    if dest.exists():shutil.copymode(dest,temp)
    os.replace(temp,dest)
print('Applied enumerated KWS startup repair; main Python environment and unrelated files preserved.')
