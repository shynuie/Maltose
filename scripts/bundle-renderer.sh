#!/bin/sh
set -eu
npm run build
mkdir -p apps/macos/MaltoseApp/Resources/renderer
cp -R packages/renderer/dist/. apps/macos/MaltoseApp/Resources/renderer/
