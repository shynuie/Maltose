#!/bin/sh
# Compatibility entry point; the product is now Maltose.
set -eu
exec "$(dirname -- "$0")/package-maltose.sh" "$@"
