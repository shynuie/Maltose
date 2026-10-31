#!/bin/sh
set -eu
export CLANG_MODULE_CACHE_PATH="$PWD/.build/module-cache"
export SWIFTPM_MODULECACHE_OVERRIDE="$PWD/.build/module-cache"
swift test --disable-sandbox --scratch-path .build --cache-path .build/cache --config-path .build/config --security-path .build/security "$@"
