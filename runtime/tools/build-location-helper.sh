#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd)"
APP_DIR="${MALTOSE_LOCATION_HELPER_DIR:-$ROOT_DIR/tools/location_helper.app}"
mkdir -p "$APP_DIR/Contents/MacOS"

cat > "$APP_DIR/Contents/Info.plist" <<'PLIST'
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
    <key>CFBundleExecutable</key>
    <string>location_helper</string>
    <key>CFBundleIdentifier</key>
    <string>com.myagent.location-helper</string>
    <key>CFBundleName</key>
    <string>Maltose Location Helper</string>
    <key>CFBundlePackageType</key>
    <string>APPL</string>
    <key>NSLocationWhenInUseUsageDescription</key>
    <string>Maltose uses your approximate location when you explicitly request it.</string>
    <key>NSLocationUsageDescription</key>
    <string>Maltose uses your approximate location when you explicitly request it.</string>
</dict>
</plist>
PLIST

swiftc \
  -framework CoreLocation \
  -framework Foundation \
  "$ROOT_DIR/tools/location_helper.swift" \
  -o "$APP_DIR/Contents/MacOS/location_helper"

# Sign the app bundle so macOS associates Core Location permission with the
# bundle identifier declared in Info.plist instead of the bare executable.
codesign --force --deep --sign - "$APP_DIR"

echo "Built $APP_DIR"
