#!/bin/sh
set -eu
python3 scripts/build-toolkit.py
./scripts/bundle-renderer.sh
export CLANG_MODULE_CACHE_PATH="$PWD/.build/module-cache"
export SWIFTPM_MODULECACHE_OVERRIDE="$PWD/.build/module-cache"
swift build -c release --disable-sandbox --scratch-path .build --cache-path .build/cache --config-path .build/config --security-path .build/security
app="dist/Maltose UI Host.app"
mkdir -p "$app/Contents/MacOS" "$app/Contents/Resources"
cp .build/release/MaltoseApp "$app/Contents/MacOS/MaltoseApp"
cp -R .build/release/MaltoseUIHost_MaltoseApp.bundle "$app/Contents/Resources/"
cp -R .build/release/MaltoseUIHost_MaltoseCore.bundle "$app/Contents/Resources/"
cat > "$app/Contents/Info.plist" <<'PLIST'
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0"><dict>
<key>CFBundleExecutable</key><string>MaltoseApp</string>
<key>CFBundleIdentifier</key><string>local.maltose.ui-host</string>
<key>CFBundleName</key><string>Maltose UI Host</string>
<key>CFBundleDisplayName</key><string>Maltose UI Host</string>
<key>CFBundlePackageType</key><string>APPL</string>
<key>CFBundleShortVersionString</key><string>0.4.0</string>
<key>CFBundleVersion</key><string>5</string>
<key>LSMinimumSystemVersion</key><string>14.0</string>
<key>NSHighResolutionCapable</key><true/>
</dict></plist>
PLIST
codesign --force --sign - "$app"
codesign --verify --strict "$app"
printf '%s\n' "Built: $app (local ad-hoc signature; not notarized)"
