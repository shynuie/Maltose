"""Resource recovery must remove exact owned IDs and never replay a creation."""
from pathlib import Path
import json
import os
import stat
import tempfile
import unittest
from unittest.mock import patch, Mock

from maltose.runtime.resources import DockerResources, ResourceCleanupError


class NativeResourceTests(unittest.TestCase):
    execution='a'*32
    scope='b'*32
    container='c'*64

    def record(self, *, phase='created', identity=None, finished=True):
        return dict(schemaVersion=1,scope=self.scope,executionID=self.execution,phase=phase,
                    containerID=identity,creationFinished=finished,creator=None)

    def test_recovery_removes_only_recorded_id_and_never_creates_or_starts(self):
        with tempfile.TemporaryDirectory() as directory:
            resources=DockerResources(Path(directory),'/installed/docker',self.scope)
            resources.save(self.record(identity=self.container))
            backend=Mock();backend._owned_container_identity.return_value=self.container
            with patch.object(resources,'backend',return_value=backend), patch.object(resources,'create') as create:
                resources.recover()
                create.assert_not_called()
                backend._remove_owned_container.assert_called_once_with('maltose-exec-'+self.execution,
                    self.execution,expected_identity=self.container)
            self.assertEqual(resources.read(self.execution)['phase'],'cleaned')
            self.assertEqual(stat.S_IMODE((Path(directory)/(self.execution+'.json')).stat().st_mode),0o600)

    def test_creation_uncertainty_stays_pending_instead_of_replaying_or_claiming_cleanup(self):
        with tempfile.TemporaryDirectory() as directory:
            resources=DockerResources(Path(directory),'/installed/docker',self.scope)
            resources.save(self.record(phase='creating',finished=False))
            backend=Mock();backend._owned_container_identity.return_value=None
            with patch.object(resources,'backend',return_value=backend),patch.object(resources,'create') as create:
                with self.assertRaisesRegex(ResourceCleanupError,'unconfirmed'): resources.recover()
                backend._remove_owned_container.assert_not_called();create.assert_not_called()
            self.assertEqual(resources.read(self.execution)['phase'],'uncertain')

    def test_lost_create_reply_recovers_owned_full_id_before_removing(self):
        with tempfile.TemporaryDirectory() as directory:
            resources=DockerResources(Path(directory),'/installed/docker',self.scope)
            resources.save(self.record(phase='creating',finished=False))
            backend=Mock();backend._owned_container_identity.return_value=self.container
            def remove(*args,**kwargs):
                self.assertEqual(resources.read(self.execution)['containerID'],self.container,
                                 'Recovered ID must be durable before destructive cleanup')
                self.assertEqual(kwargs['expected_identity'],self.container)
            backend._remove_owned_container.side_effect=remove
            with patch.object(resources,'backend',return_value=backend): resources.recover()
            self.assertEqual(resources.read(self.execution)['phase'],'cleaned')

    def test_daemon_unavailable_preserves_receipt_and_recovery_blocks_readiness(self):
        with tempfile.TemporaryDirectory() as directory:
            resources=DockerResources(Path(directory),None,self.scope)
            resources.save(self.record(identity=self.container))
            with self.assertRaisesRegex(ResourceCleanupError,'unavailable'):resources.recover()
            self.assertEqual(resources.read(self.execution)['phase'],'created')

    def test_scope_and_symlink_receipts_cannot_authorize_cleanup(self):
        with tempfile.TemporaryDirectory() as directory:
            resources=DockerResources(Path(directory),'/installed/docker','d'*32)
            resources.save(self.record(identity=self.container))
            with patch.object(resources,'backend') as backend:
                with self.assertRaisesRegex(ResourceCleanupError,'another runtime'):resources.cleanup(self.execution,current_scope=True)
                backend.assert_not_called()
            path=Path(directory)/(self.execution+'.json');path.unlink()
            original=Path(directory)/'original';original.write_text(json.dumps(self.record(identity=self.container)))
            path.symlink_to(original)
            with patch.object(resources,'backend') as backend:
                with self.assertRaises(OSError):resources.recover()
                backend.assert_not_called()
            self.assertTrue(original.exists())

    def test_already_registered_identity_cannot_launch_another_create(self):
        with tempfile.TemporaryDirectory() as directory:
            resources=DockerResources(Path(directory),'/installed/docker',self.scope)
            resources.save(self.record(identity=self.container))
            command=['/installed/docker','run','--name','maltose-exec-'+self.execution,
                     '--label','dev.maltose.execution-id='+self.execution,'image','command']
            with patch('maltose.runtime.resources.subprocess.Popen') as launch:
                with self.assertRaisesRegex(ResourceCleanupError,'already registered'):resources.create(self.execution,command)
                launch.assert_not_called()

    def test_uncertain_cleanup_closes_admission_before_runtime_is_signalled(self):
        from maltose.runtime.lifetime import NativeRuntimeLifetime
        from maltose.runtime.control import AutonomyControl, AutonomyPaused
        control=AutonomyControl(); lifetime=NativeRuntimeLifetime.__new__(NativeRuntimeLifetime)
        lifetime._control=control; lifetime.failed=False; lifetime.owner_disconnected=Mock()
        def signalled(*args):
            self.assertEqual(control.snapshot()['state'],'closed')
            with self.assertRaises(AutonomyPaused):
                with control.activity('late-write'): self.fail('New writes must not be admitted')
        with patch('maltose.runtime.lifetime.os.kill',side_effect=signalled):
            with self.assertRaisesRegex(RuntimeError,'unconfirmed'):lifetime.fail_closed('unconfirmed container cleanup')
        self.assertTrue(lifetime.failed);lifetime.owner_disconnected.assert_called_once()


    def test_pending_daemon_cleanup_blocks_runtime_start_and_retry_never_replays(self):
        import subprocess,sys
        with tempfile.TemporaryDirectory() as directory:
            base=Path(directory); binaries=base/'bin';binaries.mkdir()
            unavailable=base/'unavailable';unavailable.touch()
            calls=base/'docker-calls'; entered=base/'main-entered'
            executable=binaries/'docker'
            executable.write_text('#!'+sys.executable+'\n'+
                'import sys,json\nfrom pathlib import Path\n'+
                'base=Path('+repr(str(base))+')\n'+
                'with (base/"docker-calls").open("a") as f:f.write(json.dumps(sys.argv[1:])+"\\n")\n'+
                'raise SystemExit(1 if (base/"unavailable").exists() else 0)\n')
            executable.chmod(0o700)
            resources=DockerResources(base/'native-executions',str(executable),self.scope)
            resources.save(self.record(identity=self.container))
            program="""import sys
from pathlib import Path
from maltose.agent import cli
original=cli.main
def observed(**kwargs):
 Path(sys.argv[1]).touch()
 sys.argv=['maltose','--native-stdio','--native-text-only','--brain','echo','--config',sys.argv[2]]
 return original(**kwargs)
cli.main=observed
from maltose.desktop import main
main()
"""
            environment={**os.environ,'PYTHONPATH':str(Path(__file__).resolve().parents[1]),
                         'PATH':str(binaries)+os.pathsep+os.environ.get('PATH','')}
            arguments=[sys.executable,'-c',program,str(entered),str(base/'none.toml'),'--config',str(base/'none.toml')]
            requests=''.join(json.dumps(dict(schemaVersion=1,requestID=i,method=m))+'\n'
                for i,m in [('initialize','initialize'),('stop','shutdown')])
            blocked=subprocess.run(arguments,input=requests,text=True,capture_output=True,cwd=base,env=environment,timeout=15)
            self.assertNotEqual(blocked.returncode,0)
            self.assertFalse(entered.exists(),'Models/Agent initialization must not start before pending cleanup')
            self.assertNotIn('"notification": "ready"',blocked.stdout)
            self.assertEqual(resources.read(self.execution)['phase'],'created')
            unavailable.unlink()
            recovered=subprocess.run(arguments,input=requests,text=True,capture_output=True,cwd=base,env=environment,timeout=15)
            self.assertEqual(recovered.returncode,0,recovered.stderr)
            self.assertTrue(entered.exists());self.assertEqual(resources.read(self.execution)['phase'],'cleaned')
            operations=[json.loads(line)[0] for line in calls.read_text().splitlines()]
            self.assertNotIn('create',operations);self.assertNotIn('start',operations);self.assertNotIn('run',operations)


    def test_creator_eof_before_admission_never_executes_daemon_request(self):
        import subprocess,sys
        with tempfile.TemporaryDirectory() as directory:
            marker=Path(directory)/'executed'
            child=subprocess.Popen([sys.executable,'-m','maltose.runtime.worker','--exec-after-ready',
                sys.executable,'-c','from pathlib import Path;import sys;Path(sys.argv[1]).touch()',str(marker)],
                stdin=subprocess.PIPE,stdout=subprocess.PIPE,stderr=subprocess.PIPE)
            child.communicate(timeout=5)
            self.assertEqual(child.returncode,0);self.assertFalse(marker.exists())
            resources=DockerResources(Path(directory),None,self.scope)
            record=self.record(phase='creating',finished=False)
            record.update(admissionVersion=1,launchPermitted=False)
            resources.save(record)
            resources.recover()  # No Docker dependency: the request was never admitted.
            self.assertEqual(resources.read(self.execution)['phase'],'cleaned')


if __name__=='__main__':unittest.main()
