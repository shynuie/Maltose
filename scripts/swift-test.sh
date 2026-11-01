#!/bin/sh
set -eu
build_directory=${MALTOSE_BUILD_DIRECTORY:-"$PWD/.build"}
export CLANG_MODULE_CACHE_PATH="$build_directory/module-cache"
export SWIFTPM_MODULECACHE_OVERRIDE="$build_directory/module-cache"
swift test --disable-sandbox --scratch-path "$build_directory" --cache-path "$build_directory/cache" --config-path "$build_directory/config" --security-path "$build_directory/security" "$@"
