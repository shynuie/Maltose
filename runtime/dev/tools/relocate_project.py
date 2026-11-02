"""Recoverable, same-volume developer checkout relocation; never imports data again."""
from __future__ import annotations
import argparse
import ctypes
import fcntl
import hashlib
import json
import os
from pathlib import Path
import stat
import subprocess
import sys
import tomllib

from maltose.migration import atomic_json, encode_toml
from maltose.runtime.ownership import RuntimeLease


def git(root, *arguments):
    return subprocess.check_output(['/usr/bin/git', '-c', 'core.hooksPath=/dev/null', '-c', 'core.fsmonitor=false',
        '-c', 'core.untrackedCache=false', '-C', str(root), *arguments], stderr=subprocess.DEVNULL)


def private_read(path):
    fd=os.open(path, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK)
    with os.fdopen(fd, 'rb') as stream:
        info=os.fstat(stream.fileno())
        if not stat.S_ISREG(info.st_mode) or info.st_uid != os.getuid() or info.st_mode & 0o077 or info.st_nlink != 1:
            raise PermissionError('Relocation state must be an owner-only regular file')
        if info.st_size > 16*1024*1024: raise ValueError('Relocation state exceeds its size limit')
        return stream.read()


def digest(data): return hashlib.sha256(data).hexdigest()


def sync_directory(path):
    descriptor=os.open(path,os.O_RDONLY|os.O_DIRECTORY)
    try: os.fsync(descriptor)
    finally: os.close(descriptor)


def snapshot(root):
    names=set(git(root,'ls-files','--cached','--others','--exclude-standard','-z').split(b'\0'))-{b''}
    result=hashlib.sha256()
    for name in sorted(names):
        path=root/os.fsdecode(name)
        if path.is_symlink(): content=b'link\0'+os.fsencode(os.readlink(path))
        elif path.is_file(): content=b'file\0'+path.read_bytes()+b'\0'+str(stat.S_IMODE(path.stat().st_mode)).encode()
        elif not path.exists(): content=b'deleted'
        else: raise ValueError('Nested repositories or non-file source entries require explicit relocation')
        result.update(name+b'\0'+hashlib.sha256(content).digest())
    return dict(head=git(root,'rev-parse','HEAD').decode().strip(), sourceSHA256=result.hexdigest(),
        statusSHA256=digest(git(root,'status','--porcelain=v1','--untracked-files=all')), sourceFiles=len(names))


def translate(value, source, target):
    if not isinstance(value,str): return value
    if value==str(source): return str(target)
    if value.startswith(str(source)+'/'): return str(target)+value[len(str(source)):]
    return value


def configuration(data, source, target):
    original=tomllib.loads(data.decode())
    updated=tomllib.loads(data.decode())
    references=[]
    def visit(value, keys=()):
        if isinstance(value,dict):
            for key,item in value.items(): visit(item,(*keys,key))
        elif isinstance(value,list):
            for index,item in enumerate(value): visit(item,(*keys,str(index)))
        elif translate(value,source,target)!=value: references.append(keys)
    visit(original)
    if any(keys!=('taskbrain','codex_cwd') for keys in references):
        raise ValueError('Additional operational paths require an explicit migration; no blanket replacement')
    if not references: return data
    updated['taskbrain']['codex_cwd']=translate(original['taskbrain']['codex_cwd'],source,target)
    # The existing serializer proves the complete parsed meaning is retained.
    return encode_toml(updated).encode()


def rename_exclusive(source, target):
    library=ctypes.CDLL(None,use_errno=True)
    if sys.platform=='darwin':
        function=library.renamex_np
        function.argtypes=[ctypes.c_char_p,ctypes.c_char_p,ctypes.c_uint]
        result=function(os.fsencode(source),os.fsencode(target),4)  # RENAME_EXCL
    elif hasattr(library,'renameat2'):
        function=library.renameat2
        function.argtypes=[ctypes.c_int,ctypes.c_char_p,ctypes.c_int,ctypes.c_char_p,ctypes.c_uint]
        result=function(-100,os.fsencode(source),-100,os.fsencode(target),1)  # RENAME_NOREPLACE
    else: raise RuntimeError('Exclusive directory rename is unavailable')
    if result: raise OSError(ctypes.get_errno(),'Exclusive directory relocation failed')


class ProjectRelocation:
    def __init__(self, source, target, support):
        self.source=Path(source).expanduser().absolute()
        self.target=Path(target).expanduser().absolute()
        self.support=Path(support).expanduser().absolute()
        if self.source==self.target or self.source.parent.resolve()!=self.target.parent.resolve():
            raise ValueError('Relocation requires distinct sibling directories on the same volume')
        if self.support.is_symlink() or any(self.support.resolve().is_relative_to(path.resolve()) for path in (self.source,self.target)):
            raise ValueError('Application Support must be a separate real directory')
        self.directory=self.support/'migrations'/'project-relocation-v1'
        self.receipt=self.directory/'receipt.json'
        self.config=self.support/'maltose.toml'

    def inspect(self):
        if self.source.is_symlink() or not self.source.is_dir(): raise ValueError('Source must be the real checkout directory')
        if os.path.lexists(self.target): raise FileExistsError('Destination already exists; nothing will be overwritten')
        if not (self.source/'.git').is_dir() or (self.source/'.git').is_symlink(): raise ValueError('Select the main Git checkout')
        if Path(os.fsdecode(git(self.source,'rev-parse','--show-toplevel')).strip()).resolve()!=self.source.resolve():
            raise ValueError('Source is not the Git root')
        if not (self.source/'Package.swift').is_file() or not (self.source/'runtime/pyproject.toml').is_file():
            raise ValueError('Expected the unified Maltose checkout')
        # Active product tasks require versioned task/worktree relocation, not
        # rewriting their messages or Codex-owned thread storage as plain strings.
        for name in ('tasks.json','repositories.json'):
            path=self.support/'collaboration'/name
            if path.exists():
                value=json.loads(private_read(path))
                if value.get('tasks') or value.get('inputs') or value.get('authorized') or any(
                    c.get('inputs') or c.get('worktreePath') for c in value.get('conversations',[]) or []):
                    raise ValueError('Saved development tasks require explicit relocation before moving this checkout')
        data=private_read(self.config)
        rewritten=configuration(data,self.source,self.target)
        info=self.source.stat()
        return dict(schemaVersion=1,source=str(self.source),target=str(self.target),device=info.st_dev,inode=info.st_ino,
            before=snapshot(self.source),configBeforeSHA256=digest(data),configAfterSHA256=digest(rewritten),
            developmentEnvironmentRequiresRebuild=(self.source/'runtime/.venv').exists())

    def run(self):
        self.support.mkdir(parents=True,exist_ok=True,mode=0o700)
        with RuntimeLease(self.support):
            collaboration=self.support/'collaboration'
            if collaboration.is_symlink(): raise PermissionError('Collaboration directory cannot be a symbolic link')
            collaboration.mkdir(mode=0o700,exist_ok=True)
            fd=os.open(collaboration/'tasks.json.lock',os.O_RDWR|os.O_CREAT|os.O_NOFOLLOW,0o600)
            with os.fdopen(fd,'r+b') as lease:
                fcntl.flock(lease,fcntl.LOCK_EX|fcntl.LOCK_NB)
                return self._run_locked()

    def _run_locked(self):
        if any(path.is_symlink() for path in (self.support/'migrations',self.directory)):
            raise PermissionError('Relocation directory cannot be a symbolic link')
        if self.receipt.exists():
            state=json.loads(private_read(self.receipt))
            if state.get('schemaVersion')!=1 or state.get('source')!=str(self.source) or state.get('target')!=str(self.target):
                raise ValueError('Relocation receipt belongs to another operation')
        else:
            state={**self.inspect(),'phase':'prepared'}
            self.directory.mkdir(parents=True,exist_ok=True,mode=0o700)
            backup=self.directory/'config-before.toml'
            if backup.exists():
                if digest(private_read(backup))!=state['configBeforeSHA256']: raise ValueError('A different relocation backup already exists')
            else:
                with backup.open('xb') as stream:
                    os.chmod(backup,0o600); stream.write(private_read(self.config)); stream.flush(); os.fsync(stream.fileno())
            atomic_json(self.receipt,state)
        original=private_read(self.directory/'config-before.toml')
        updated=configuration(original,self.source,self.target)
        if digest(original)!=state['configBeforeSHA256'] or digest(updated)!=state['configAfterSHA256']:
            raise ValueError('Relocation configuration backup changed')
        if not os.path.lexists(self.target):
            if self.source.is_symlink() or (self.source.stat().st_dev,self.source.stat().st_ino)!=(state['device'],state['inode']):
                raise ValueError('Source identity changed since relocation was prepared')
            if snapshot(self.source)!=state['before'] or digest(private_read(self.config))!=state['configBeforeSHA256']:
                raise ValueError('Checkout or configuration changed; prepared relocation cannot overwrite it')
            rename_exclusive(self.source,self.target)
            sync_directory(self.target.parent)
        if self.target.is_symlink() or (self.target.stat().st_dev,self.target.stat().st_ino)!=(state['device'],state['inode']):
            raise ValueError('Destination is not the original checkout')
        if not os.path.lexists(self.source):
            os.symlink(self.target,self.source,target_is_directory=True)
            sync_directory(self.source.parent)
        if not self.source.is_symlink() or self.source.resolve()!=self.target.resolve():
            raise ValueError('Old path was reused; do not overwrite it to create a compatibility alias')
        state['phase']='moved'; atomic_json(self.receipt,state)
        current=digest(private_read(self.config))
        if current not in (state['configBeforeSHA256'],state['configAfterSHA256']):
            raise ValueError('Configuration changed during relocation; retain both copies for review')
        if current!=state['configAfterSHA256']:
            temporary=self.directory/'config-updated.toml'
            with temporary.open('wb') as stream:
                os.chmod(temporary,0o600); stream.write(updated); stream.flush(); os.fsync(stream.fileno())
            os.replace(temporary,self.config)
            sync_directory(self.config.parent)
        if snapshot(self.target)!=state['before']: raise ValueError('Checkout changed during relocation; inspect the retained receipt')
        state['phase']='relocated'; atomic_json(self.receipt,state)
        sync_directory(self.directory)
        return dict(phase=state['phase'],source=str(self.source),target=str(self.target),sourceFiles=state['before']['sourceFiles'],
            sourceUnchanged=True,configurationUpdated=True,compatibilityAlias=True,
            developmentEnvironmentRequiresRebuild=state['developmentEnvironmentRequiresRebuild'])


if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--source',type=Path,required=True); parser.add_argument('--target',type=Path,required=True)
    parser.add_argument('--support',type=Path,required=True); parser.add_argument('--apply',action='store_true')
    arguments=parser.parse_args()
    operation=ProjectRelocation(arguments.source,arguments.target,arguments.support)
    result=operation.run() if arguments.apply else operation.inspect()
    if not arguments.apply:
        result={key:value for key,value in result.items() if key not in ('configBeforeSHA256','configAfterSHA256','before','device','inode')}
    print(json.dumps(result,ensure_ascii=False))
