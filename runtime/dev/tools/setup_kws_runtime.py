"""Rebuild only the persistent legacy KWS environment; never sync the main .venv."""
import argparse
from pathlib import Path
import shutil
import subprocess

def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--python',default='3.10',help='Python 3.10 interpreter or uv version request')
    args=parser.parse_args()
    root=Path(__file__).resolve().parents[2]
    environment=root/'.venvs/kws310'
    python=environment/'bin/python'
    if not shutil.which('uv'):parser.exit(2,'請先安裝 uv。\n')
    if not python.exists():
        if environment.exists():parser.exit(2,f'隔離環境不完整，請先檢查而非覆寫：{environment}\n')
        subprocess.run(['uv','venv','--python',args.python,str(environment)],check=True)
    version=subprocess.run([str(python),'-c','import sys;assert sys.version_info[:2]==(3,10)'],capture_output=True)
    if version.returncode:parser.exit(2,'KWS 隔離環境必須使用 Python 3.10。\n')
    requirements=root/'dev/tools/kws-runtime/requirements.txt'
    subprocess.run(['uv','pip','sync','--python',str(python),'--require-hashes','--find-links','https://modelscope.oss-cn-beijing.aliyuncs.com/releases/repo.html',str(requirements)],check=True)
    subprocess.run([str(python),'-c','import torch, py_sound_connect; from modelscope.pipelines import pipeline'],check=True)
    print(f'KWS 環境已備妥：{python}\nwake.toml: python = ".venvs/kws310/bin/python"')
if __name__=='__main__':main()
