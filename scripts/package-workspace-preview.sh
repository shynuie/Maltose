#!/bin/sh
set -eu
export CLANG_MODULE_CACHE_PATH="$PWD/.build/module-cache"
export SWIFTPM_MODULECACHE_OVERRIDE="$PWD/.build/module-cache"
swift build -c release --product MaltoseApp --disable-sandbox --scratch-path .build --cache-path .build/cache --config-path .build/config --security-path .build/security
preview="dist/Maltose Workspace Preview.app"
stage=".cache/ui-preview/Maltose Workspace Preview.app"
rm -rf "$stage"
mkdir -p "$stage/Contents/MacOS"
cp .build/release/MaltoseApp "$stage/Contents/MacOS/MaltoseApp"
python3 - <<'PY'
import plistlib
from pathlib import Path
path = Path('.cache/ui-preview/Maltose Workspace Preview.app/Contents/Info.plist')
data = dict(CFBundleExecutable='MaltoseApp', CFBundleIdentifier='local.maltose.workspace-preview',
            CFBundleName='Maltose Workspace Preview', CFBundleDisplayName='Maltose Workspace Preview',
            CFBundlePackageType='APPL', CFBundleShortVersionString='0.5.0', CFBundleVersion='6',
            LSMinimumSystemVersion='14.0', NSHighResolutionCapable=True)
with path.open('wb') as file:
    plistlib.dump(data, file)
PY
codesign --force --sign - "$stage"
codesign --verify --strict "$stage"
rm -rf "$preview"
mkdir -p dist
mv "$stage" "$preview"
printf '%s\n' "Built pure UI preview: $preview"
