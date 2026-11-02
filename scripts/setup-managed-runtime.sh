#!/bin/sh
# Provision dependencies for the app's bundled runtime; never copy a development venv.
set -eu
umask 077
project_root=$(CDPATH= cd -- "$(dirname -- "$0")/.." && pwd)
support=${1:-"$HOME/Library/Application Support/Maltose"}
if [ "${MALTOSE_SETUP_HAS_LEASE:-}" != "1" ]; then
    exec python3 - "$support" "$project_root/scripts/setup-managed-runtime.sh" <<'LEASE'
import fcntl,os,subprocess,sys
from pathlib import Path
support=Path(sys.argv[1]).expanduser().resolve()
support.mkdir(parents=True,exist_ok=True,mode=0o700)
descriptor=os.open(support/'.native-runtime.lock',os.O_RDWR|os.O_CREAT|os.O_NOFOLLOW,0o600)
with os.fdopen(descriptor,'a') as lease:
    try: fcntl.flock(lease.fileno(),fcntl.LOCK_EX|fcntl.LOCK_NB)
    except BlockingIOError:
        print('Quit Maltose before provisioning or repairing its active Python environments.',file=sys.stderr)
        raise SystemExit(2)
    environment={**os.environ,'MALTOSE_SETUP_HAS_LEASE':'1'}
    raise SystemExit(subprocess.call(['/bin/sh',sys.argv[2],str(support)],env=environment))
LEASE
fi
environments="$support/environments"
mkdir -p "$environments"
requirements=$(mktemp "${TMPDIR:-/tmp}/maltose-managed-requirements.XXXXXX")
trap 'rm -f "$requirements"' EXIT HUP INT TERM

prepare_environment() {
    name=$1
    version=$2
    interpreter=${3:-$version}
    target="$environments/$name"
    ownership="$environments/.$name-maltose-v1"
    if [ -e "$target" ] && [ ! -f "$ownership" ]; then
        echo "Refusing to replace an environment without a Maltose ownership record: $target" >&2
        exit 2
    fi
    : > "$ownership"
    if [ ! -x "$target/bin/python" ]; then
        uv venv --python "$interpreter" --no-python-downloads "$target"
    fi
    "$target/bin/python" -c 'import sys; assert ".".join(map(str,sys.version_info[:3])) == sys.argv[1], "Managed Python version mismatch"' "$version"
}

prepare_environment main 3.12.10 "${MALTOSE_MAIN_PYTHON:-3.12.10}"
uv export --project "$project_root/runtime" --locked --extra desktop --extra codex --extra wake --extra qwen-asr --extra vector-memory --extra speaker --no-emit-project --format requirements-txt > "$requirements"
uv pip sync --python "$environments/main/bin/python" --require-hashes "$requirements"
# Code is loaded from Maltose.app/Contents/Resources/Runtime, not an editable checkout.
"$environments/main/bin/python" -c 'import sounddevice, torch, lancedb, sentence_transformers; print("Managed main dependencies ready")'

prepare_environment kws310 3.10.19 "${MALTOSE_KWS_PYTHON:-3.10.19}"
uv pip sync --python "$environments/kws310/bin/python" --require-hashes --find-links https://modelscope.oss-cn-beijing.aliyuncs.com/releases/repo.html "$project_root/runtime/dev/tools/kws-runtime/requirements.txt"
"$environments/kws310/bin/python" -c 'import torch, py_sound_connect; from modelscope.pipelines import pipeline; print("Managed KWS dependencies ready")'

"$environments/main/bin/python" - "$project_root" "$support" <<'PY'
import hashlib,json,sys
from pathlib import Path
project, support = map(Path,sys.argv[1:])
receipt = {'schemaVersion':1,'mainPython':'3.12.10','kwsPython':'3.10.19',
    'mainLockSHA256':hashlib.sha256((project/'runtime/uv.lock').read_bytes()).hexdigest(),
    'kwsLockSHA256':hashlib.sha256((project/'runtime/dev/tools/kws-runtime/requirements.txt').read_bytes()).hexdigest()}
path=support/'environments/provisioning-v1.json'
path.write_text(json.dumps(receipt,indent=2)+'\n'); path.chmod(0o600)
print('Managed Maltose dependencies provisioned; application data was not changed.')
PY
