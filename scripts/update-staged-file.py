"""Refresh manifests after a focused correction to already-applied integration files."""
from pathlib import Path
import hashlib,json
root=Path(__file__).resolve().parents[1];stage=root/'.cache/myagent-edit';target=Path('/Users/Marvin/Workspace/MyAgent')
p=stage/'apply-manifest.json';entries=json.loads(p.read_text())
for entry in entries:
    source=stage/entry['path'];dest=target/entry['path']
    new=hashlib.sha256(source.read_bytes()).hexdigest()
    if new!=entry['sha256']:
        if dest.exists():entry['original']=hashlib.sha256(dest.read_bytes()).hexdigest()
        entry['sha256']=new
p.write_text(json.dumps(entries,indent=2))
