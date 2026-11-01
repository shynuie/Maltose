#!/usr/bin/env python3
"""Verify the local App bundle against source without initializing an Agent."""
from __future__ import annotations
import argparse
import hashlib
import json
import os
from pathlib import Path
import plistlib
import subprocess
import sys
import tempfile


def verify(root: Path, app: Path, python: Path, credentials: list[Path]) -> dict:
    root=root.resolve(); app=app.absolute()
    if app.is_symlink() or not app.is_dir(): raise ValueError('App must be a real directory')
    files=[]
    forbidden={'.env','auth.json','maltose.toml','myagent.toml','wake.toml','credentials.json'}
    forbidden_directories={'.venv','.venvs','models','recordings','node_modules','__pycache__'}
    for path in app.rglob('*'):
        if path.is_symlink(): raise ValueError('App contains a symbolic link: '+str(path.relative_to(app)))
        relative=path.relative_to(app)
        if path.name in forbidden or path.name.startswith('.env.') or path.name in forbidden_directories:
            raise ValueError('App contains private configuration/data/environment: '+str(relative))
        if path.is_file():
            if path.suffix.lower() in {'.db','.sqlite','.sqlite3','.lance','.pyc'}: raise ValueError('App contains runtime state: '+str(relative))
            files.append(path)
    info=plistlib.loads((app/'Contents/Info.plist').read_bytes())
    if info.get('CFBundleIdentifier')!='local.maltose.app' or info.get('CFBundleDisplayName')!='Maltose': raise ValueError('Product identity is incorrect')
    if not info.get('NSMicrophoneUsageDescription'): raise ValueError('Microphone purpose is missing')
    if not os.access(app/'Contents/MacOS/MaltoseApp',os.X_OK): raise ValueError('App executable is missing')
    runtime=app/'Contents/Resources/Runtime'
    source=root/'runtime/maltose'
    expected={str(path.relative_to(source)):hashlib.sha256(path.read_bytes()).hexdigest() for path in source.rglob('*')
              if path.is_file() and '__pycache__' not in path.parts and path.suffix!='.pyc'}
    packaged={str(path.relative_to(runtime/'maltose')):hashlib.sha256(path.read_bytes()).hexdigest()
              for path in (runtime/'maltose').rglob('*') if path.is_file()}
    for name in packaged:
        if not name.endswith('.py') and name not in {'web/static/index.html','ui/_bootstrap/publisher.pem'}:
            raise ValueError('Unexpected non-code runtime resource: '+name)
    if expected!=packaged:
        changed=sorted(key for key in expected.keys()|packaged.keys() if expected.get(key)!=packaged.get(key))
        raise ValueError('Packaged runtime differs from current source: '+', '.join(changed[:12]))
    sys.path.insert(0,str(root/'runtime'))
    from maltose.runtime.environment import load_private_environment
    values={}
    for path in credentials: load_private_environment(path,environ=values)
    needles=[value.encode() for value in values.values() if value]
    for path in files:
        data=path.read_bytes()
        if any(value in data for value in needles): raise ValueError('App includes a configured service credential value: '+str(path.relative_to(app)))
    signed=subprocess.run(['/usr/bin/codesign','--verify','--deep','--strict',str(app)],capture_output=True)
    if signed.returncode: raise ValueError('Strict App code-signature verification failed')
    environment={**os.environ,'PYTHONPATH':str(runtime),'PYTHONDONTWRITEBYTECODE':'1'}
    program="""from pathlib import Path
import sys,maltose
from maltose.codex import review,native_service,native_tools,lifetime,runner
from maltose.ui import native
from maltose.runtime import lifetime as native_lifetime,processes,resources
base=Path(sys.argv[1]).resolve()
for module in (maltose,review,native_service,native_tools,lifetime,runner,native,native_lifetime,processes,resources):
    assert Path(module.__file__).resolve().is_relative_to(base)
"""
    with tempfile.TemporaryDirectory(prefix='maltose-package-import-') as directory:
        imported=subprocess.run([str(python),'-c',program,str(runtime)],cwd=directory,env=environment,capture_output=True,timeout=30)
    if imported.returncode: raise ValueError('Packaged runtime import from independent cwd failed; no Agent was initialized')
    return dict(version=info.get('CFBundleShortVersionString'),build=info.get('CFBundleVersion'),bundleFiles=len(files),
        runtimeFiles=len(packaged),runtimeMatchesSource=True,configuredCredentialValuesChecked=len(needles),
        signature='passed',independentRuntimeImport='passed',agentStarted=False,microphoneUsed=False)


if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--root',type=Path,default=Path(__file__).resolve().parents[1])
    parser.add_argument('--app',type=Path)
    parser.add_argument('--python',type=Path,required=True)
    parser.add_argument('--credential-file',type=Path,action='append',default=[])
    args=parser.parse_args()
    print(json.dumps(verify(args.root,args.app or args.root/'dist/Maltose.app',args.python,args.credential_file)))
