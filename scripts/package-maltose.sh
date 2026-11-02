#!/bin/sh
set -eu
build_directory=${MALTOSE_BUILD_DIRECTORY:-"$PWD/.build"}
export CLANG_MODULE_CACHE_PATH="$build_directory/module-cache"
export SWIFTPM_MODULECACHE_OVERRIDE="$build_directory/module-cache"
swift build -c release --product MaltoseApp --disable-sandbox --scratch-path "$build_directory" --cache-path "$build_directory/cache" --config-path "$build_directory/config" --security-path "$build_directory/security"
preview=${MALTOSE_PACKAGE_OUTPUT:-"dist/Maltose.app"}
stage=".cache/ui-preview/Maltose.app"
rm -rf "$stage"
mkdir -p "$stage/Contents/MacOS"
cp "$build_directory/release/MaltoseApp" "$stage/Contents/MacOS/MaltoseApp"
cp -R "$build_directory/release/Maltose_MaltoseApp.bundle" "$stage/Contents/MacOS/"
if [ -d data/imgs/demo ]; then
    mkdir -p "$stage/Contents/Resources/GallerySamples"
    cp data/imgs/demo/* "$stage/Contents/Resources/GallerySamples/"
fi
python3 - <<'PY'
import os
import plistlib
from pathlib import Path
path = Path('.cache/ui-preview/Maltose.app/Contents/Info.plist')
data = dict(CFBundleExecutable='MaltoseApp', CFBundleIdentifier='local.maltose.app',
            CFBundleName='Maltose', CFBundleDisplayName='Maltose',
            CFBundlePackageType='APPL', CFBundleShortVersionString='0.7.0', CFBundleVersion=os.environ.get('MALTOSE_PACKAGE_BUILD', '15'),
            LSMinimumSystemVersion='14.0', NSHighResolutionCapable=True,
            NSMicrophoneUsageDescription='Maltose 使用麥克風接收語音指令、辨識喚醒詞與說話者。')
with path.open('wb') as file:
    plistlib.dump(data, file)
resource_bundle = Path('.cache/ui-preview/Maltose.app/Contents/MacOS/Maltose_MaltoseApp.bundle')
resource_info = dict(CFBundleIdentifier='local.maltose.app.resources',
                     CFBundleName='Maltose_MaltoseApp', CFBundlePackageType='BNDL')
with (resource_bundle / 'Info.plist').open('wb') as file:
    plistlib.dump(resource_info, file)
PY
python3 - <<'PYRUNTIME'
from pathlib import Path
import shutil
source = Path('runtime/maltose')
target = Path('.cache/ui-preview/Maltose.app/Contents/Resources/Runtime/maltose')
shutil.copytree(source, target, ignore=shutil.ignore_patterns('__pycache__', '*.pyc'))
PYRUNTIME
codesign --force --sign - "$stage/Contents/MacOS/Maltose_MaltoseApp.bundle"
codesign --force --sign - "$stage"
codesign --verify --strict "$stage"
rm -rf "$preview"
mkdir -p "$(dirname -- "$preview")"
mv "$stage" "$preview"
printf '%s\n' "Built Maltose: $preview"
