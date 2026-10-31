#!/bin/sh
# Recreate the Python runtime from the existing lock without touching user data.
set -eu
project_root=$(CDPATH= cd -- "$(dirname -- "$0")/.." && pwd)
runtime_root="$project_root/runtime"
requirements=$(mktemp "${TMPDIR:-/tmp}/maltose-requirements.XXXXXX")
trap 'rm -f "$requirements"' EXIT HUP INT TERM
if [ ! -x "$runtime_root/.venv/bin/python" ]; then
    uv venv --python "${MALTOSE_PYTHON:-3.12}" --no-python-downloads "$runtime_root/.venv"
fi
uv export --project "$runtime_root" --locked --extra wake --extra qwen-asr --extra vector-memory --extra speaker --no-emit-project --format requirements-txt > "$requirements"
uv pip sync --python "$runtime_root/.venv/bin/python" --require-hashes "$requirements"
uv pip install --python "$runtime_root/.venv/bin/python" --no-deps -e "$runtime_root"
"$runtime_root/.venv/bin/python" -c 'import maltose; print("Maltose runtime ready")'
