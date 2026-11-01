import contextlib
import io
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch
from maltose.voice.alibaba_kws import AlibabaKWSDetector,AlibabaKWSProcessError
from maltose.voice.wake import load_wake_word_config

class KWSStartupTests(unittest.TestCase):
    def test_native_model_stdout_cannot_corrupt_worker_protocol(self):
        with tempfile.TemporaryDirectory() as temp:
            script=Path(temp)/'worker.py'
            script.write_text('''import os
from types import SimpleNamespace
from maltose.voice import alibaba_kws_worker as worker
class LoudRuntime:
 def __init__(self, model_dir):
  os.write(1,b'native library initialization output\\n')
  self.sample_rate=16000;self._samples_per_block=1;self._mono_buffer=bytearray()
  self.model=SimpleNamespace(_sc=SimpleNamespace(kwsState=lambda:0))
 def process(self, payload):
  os.write(1,b'native decoding output\\n');return {'hit':None,'blocks':0}
 def reset(self):os.write(1,b'native reset output\\n')
worker.AlibabaKWSRuntime=LoudRuntime
worker.main()
''')
            with patch.dict(os.environ,{'MALTOSE_KWS_LOG':str(Path(temp)/'worker.log')}):
                detector=AlibabaKWSDetector('/unused-model',python=sys.executable,worker_script=script)
            try:
                self.assertIsNone(detector.process_frame(b'\x00'*640,16000))
                detector.reset();self.assertTrue(detector.health()['healthy'])
            finally:detector.close()
    def test_coalesced_frames_are_not_hidden_by_a_buffered_pipe(self):
        with tempfile.TemporaryDirectory() as temp:
            script=Path(temp)/'worker.py'
            script.write_text('''import sys
from maltose.kws_protocol import *
def frame(kind, value):
 payload=json_bytes(value); return HEADER.pack(kind,len(payload))+payload
sys.stdout.buffer.write(frame(READY,{})+frame(RESPONSE,{'healthy':True}));sys.stdout.buffer.flush()
while True:
 message=read_message(sys.stdin.buffer)
 if message is None or message[0]==SHUTDOWN:break
''')
            detector=AlibabaKWSDetector('/unused-model',python=sys.executable,worker_script=script,timeout_seconds=.1)
            try:self.assertTrue(detector.health()['healthy'])
            finally:detector.close()

    def test_response_deadline_covers_partial_payload_not_just_first_byte(self):
        with tempfile.TemporaryDirectory() as temp:
            script=Path(temp)/'worker.py'
            script.write_text('''import sys
from maltose.kws_protocol import *
write_message(sys.stdout.buffer,READY,json_bytes({}))
while True:
 message=read_message(sys.stdin.buffer)
 if message is None or message[0]==SHUTDOWN:break
 sys.stdout.buffer.write(HEADER.pack(RESPONSE,20)+b'{');sys.stdout.buffer.flush()
''')
            detector=AlibabaKWSDetector('/unused-model',python=sys.executable,worker_script=script,timeout_seconds=.05)
            try:
                with self.assertRaisesRegex(AlibabaKWSProcessError,'timed out'):detector.health()
                self.assertIsNone(detector._process)
            finally:detector.close()

    def test_pcm_reset_and_health_transactions_do_not_consume_other_threads_replies(self):
        from concurrent.futures import ThreadPoolExecutor
        with tempfile.TemporaryDirectory() as temp:
            script=Path(temp)/'worker.py'
            script.write_text('''import sys,time
from maltose.kws_protocol import *
write_message(sys.stdout.buffer,READY,json_bytes({}))
while True:
 message=read_message(sys.stdin.buffer)
 if message is None or message[0]==SHUTDOWN:break
 kind,payload=message
 response={'hit':{'keyword':payload.decode()}} if kind==PCM else {'healthy':True} if kind==HEALTH else {'reset':True}
 data=json_bytes(response); frame=HEADER.pack(RESPONSE,len(data))+data
 for byte in frame:
  sys.stdout.buffer.write(bytes([byte]));sys.stdout.buffer.flush();time.sleep(.0001)
''')
            detector=AlibabaKWSDetector('/unused-model',python=sys.executable,worker_script=script,timeout_seconds=2)
            def request(index):
                if index%3==0:self.assertEqual(detector.process_frame(str(index).encode(),16000).keyword,str(index))
                elif index%3==1:detector.reset()
                else:self.assertTrue(detector.health()['healthy'])
            try:
                with ThreadPoolExecutor(max_workers=4) as workers:list(workers.map(request,range(24)))
            finally:detector.close()

    def test_missing_interpreter_explains_rebuild_before_starting_worker(self):
        with patch('maltose.voice.alibaba_kws.subprocess.Popen') as popen:
            with self.assertRaisesRegex(AlibabaKWSProcessError,'setup_kws_runtime.py'):
                AlibabaKWSDetector('/unused-model',python='/missing-kws/python')
            popen.assert_not_called()
    def test_non_executable_interpreter_is_rejected(self):
        with tempfile.TemporaryDirectory() as temp:
            python=Path(temp)/'python';python.write_text('not executable');python.chmod(0o600)
            with self.assertRaisesRegex(AlibabaKWSProcessError,'找不到可執行'):
                AlibabaKWSDetector('/unused-model',python=python)
    def test_config_relative_interpreter_follows_config_location(self):
        with tempfile.TemporaryDirectory() as temp:
            config=Path(temp)/'wake.toml'
            config.write_text('[wake]\nprovider="alibaba-modelscope"\n[wake.alibaba]\nmodel_dir="models/kws"\npython=".venvs/kws310/bin/python"\n')
            loaded=load_wake_word_config(config)
            self.assertEqual(loaded.alibaba.python,Path(temp)/'.venvs/kws310/bin/python')
            # venv/bin/python is normally a symlink; preserve the venv path at launch.
            python=Path(temp)/'.venvs/kws310/bin/python';python.parent.mkdir(parents=True)
            python.symlink_to(sys.executable)
            self.assertEqual(load_wake_word_config(config).alibaba.python,python)
            config.write_text(config.read_text().replace('.venvs/kws310/bin/python','python3.10'))
            self.assertEqual(load_wake_word_config(config).alibaba.python,Path('python3.10'))
    def test_worker_init_error_preserves_reason_and_reaps_child(self):
        with tempfile.TemporaryDirectory() as temp:
            script=Path(temp)/'worker.py'
            script.write_text("import sys\nfrom maltose.kws_protocol import write_message,json_bytes,ERROR\nwrite_message(sys.stdout.buffer,ERROR,json_bytes({'error':'missing test dependency'}))\n")
            actual=subprocess.Popen;children=[]
            def start(*args,**kwargs):
                process=actual(*args,**kwargs);children.append(process);return process
            with patch('maltose.voice.alibaba_kws.subprocess.Popen',side_effect=start):
                with self.assertRaisesRegex(AlibabaKWSProcessError,'missing test dependency'):
                    AlibabaKWSDetector('/unused-model',python=sys.executable,worker_script=script)
            self.assertIsNotNone(children[0].poll())
            self.assertTrue(children[0].stdin.closed and children[0].stdout.closed)
    def test_initialization_grace_does_not_relax_request_timeout(self):
        with tempfile.TemporaryDirectory() as temp:
            script=Path(temp)/'worker.py'
            script.write_text("import sys,time\nfrom maltose.kws_protocol import *\ntime.sleep(.1)\nwrite_message(sys.stdout.buffer,READY,json_bytes({}))\nwhile True:\n    message=read_message(sys.stdin.buffer)\n    if message is None or message[0]==SHUTDOWN:break\n    time.sleep(.1)\n    write_message(sys.stdout.buffer,RESPONSE,json_bytes({'healthy':True}))\n")
            detector=AlibabaKWSDetector('/unused-model',python=sys.executable,worker_script=script,startup_timeout_seconds=2,timeout_seconds=.02)
            try:
                with self.assertRaisesRegex(AlibabaKWSProcessError,'0.02s'):detector.health()
                self.assertIsNone(detector._process)
            finally:detector.close()
    def test_cli_reports_wake_error_without_traceback_or_model_start(self):
        from maltose.agent.cli import main
        with tempfile.TemporaryDirectory() as temp:
            config=Path(temp)/'wake.toml';config.write_text('[wake]\nprovider="alibaba-modelscope"\n[wake.alibaba]\nmodel_dir="models/kws"\npython="/missing/python"\n')
            output=io.StringIO()
            with patch('sys.argv',['maltose','--config',str(Path(temp)/'none.toml'),'--wake-config',str(config)]),contextlib.redirect_stderr(output):
                with self.assertRaises(SystemExit) as stopped:main()
            self.assertEqual(stopped.exception.code,2)
            self.assertIn('喚醒詞服務啟動失敗',output.getvalue());self.assertNotIn('Traceback',output.getvalue())
    def test_start_reports_agent_exit_instead_of_ui_port_failure(self):
        root=Path(__file__).resolve().parents[1]
        with tempfile.TemporaryDirectory() as temp:
            temp=Path(temp);shutil.copyfile(root/'start',temp/'start')
            bin_dir=temp/'bin';bin_dir.mkdir()
            uv=bin_dir/'uv';uv.write_text('#!/bin/sh\ncase "$*" in *maltose-documents*) exec sleep 30 ;; *) sleep 0.1; exit 23 ;; esac\n');uv.chmod(0o755)
            curl=bin_dir/'curl';curl.write_text('#!/bin/sh\nexit 1\n');curl.chmod(0o755)
            env={**os.environ,'PATH':str(bin_dir)+os.pathsep+os.environ['PATH'],'MYAGENT_OPEN_BROWSER':'1','MYAGENT_WEB_STARTUP_TIMEOUT':'3'}
            result=subprocess.run(['bash',str(temp/'start')],env=env,capture_output=True,text=True,timeout=6)
            self.assertEqual(result.returncode,23)
            self.assertIn('Maltose 已在 UI 就緒前結束',result.stderr)
            self.assertNotIn('UI did not become ready',result.stderr)
if __name__=='__main__':unittest.main()
