"""Apply only reviewed staged UI-integration files; reject concurrent or unrelated edits."""
import hashlib,json,os
from pathlib import Path
root=Path(__file__).resolve().parents[1];stage=root/'.cache/myagent-edit';destination=Path('/Users/Marvin/Workspace/MyAgent')
manifest=json.loads((stage/'apply-manifest.json').read_text())
# New test sources are explicit in this installer, rather than a broad copy of the repository.
for path in (stage/'tests').glob('test_maltose*.py'):
    baselines=json.loads((root/'.cache/myagent-test-baselines.json').read_text()) if (root/'.cache/myagent-test-baselines.json').exists() else {}
    manifest.append({'path':str(path.relative_to(stage)),'original':baselines.get(str(path.relative_to(stage))),'sha256':hashlib.sha256(path.read_bytes()).hexdigest()})
for entry in manifest:
    name=entry['path']
    if name=='apply-manifest.json' or '__pycache__' in name:continue
    assert name.startswith(('myagent/ui/','myagent/agent/','tests/test_maltose','dev/'))
    target=destination/name;source=stage/name
    assert hashlib.sha256(source.read_bytes()).hexdigest()==entry['sha256'],name
    if target.exists():
        current=hashlib.sha256(target.read_bytes()).hexdigest()
        if current==entry['sha256']:continue
        assert current==entry['original'],'Concurrent changes: '+name
    else:assert entry['original'] is None,name
for entry in manifest:
    name=entry['path']
    if name=='apply-manifest.json' or '__pycache__' in name:continue
    target=destination/name;target.parent.mkdir(parents=True,exist_ok=True)
    temp=target.with_name(target.name+'.maltose-tmp');temp.write_bytes((stage/name).read_bytes());os.replace(temp,target)
print('Applied file-scoped MyAgent native UI integration; unrelated changes preserved.')
