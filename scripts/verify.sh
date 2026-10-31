#!/bin/sh
set -eu
python3 scripts/generate-schemas.py
python3 scripts/generate-ts-schema.py
npm test
./scripts/bundle-renderer.sh
./scripts/swift-test.sh
.venv/bin/python -m pytest tests/protocol tests/integration tests/security -q
