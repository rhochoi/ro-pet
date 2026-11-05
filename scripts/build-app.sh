#!/usr/bin/env bash
# Build a standalone ro-pet.app. Result: build/ro-pet.app
#   ./scripts/build-app.sh
# Precompiles the Swift host and bundles a standalone Python (uv / python-build-standalone) plus ro_pet,
# so the user's Mac needs no Python and no swiftc.
# Env: SIGN_IDENTITY="Developer ID Application: Name (TEAMID)"  distributable signature (hardened runtime).
#      empty -> ad-hoc signature (-): only for this Mac and friends (Gatekeeper warns elsewhere).
#      PYTHON_VERSION (default 3.13)
# Apple Silicon (arm64) only.
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
BUILD="$ROOT/build"
APP="$BUILD/ro-pet.app"
PYVER="${PYTHON_VERSION:-3.13}"
IDENTITY="${SIGN_IDENTITY:--}"

say() { printf '\033[1m==>\033[0m %s\n' "$*"; }
die() { printf '\033[31merror:\033[0m %s\n' "$*" >&2; exit 1; }

[ "$(uname -s)" = Darwin ] || die "build on macOS only"
[ "$(uname -m)" = arm64 ] || die "Apple Silicon (arm64) only for now"
command -v swiftc >/dev/null || die "swiftc missing: xcode-select --install"
command -v uv >/dev/null || die "uv missing: https://astral.sh/uv"

VERSION="$(sed -n 's/^version = "\(.*\)"/\1/p' "$ROOT/pyproject.toml" | head -1)"
VERSION="${VERSION:-0.0.0}"

say "clean: $APP"
rm -rf "$APP"
mkdir -p "$APP/Contents/MacOS" "$APP/Contents/Resources/lib"

say "compile the Swift host"
swiftc -O "$ROOT/ro_pet/pet_mac.swift" -o "$APP/Contents/MacOS/ro-pet-host" \
  -framework AppKit -framework WebKit

say "standalone Python $PYVER (uv, downloaded on first run)"
PYCACHE="$BUILD/python-cache"
uv python install "$PYVER" --install-dir "$PYCACHE" >/dev/null
PYSRC="$(find "$PYCACHE" -maxdepth 1 -type d -name "cpython-$PYVER*" | head -1)"
[ -n "$PYSRC" ] || die "standalone Python not found in $PYCACHE"
cp -RL "$PYSRC" "$APP/Contents/Resources/python"
PYLIB="$APP/Contents/Resources/python/lib/python$PYVER"
rm -rf "$PYLIB/test" "$PYLIB/idlelib" "$PYLIB/turtledemo" "$PYLIB/tkinter" \
       "$PYLIB/ensurepip" "$PYLIB/site-packages/pip"* "$APP/Contents/Resources/python/share"
rm -rf "$APP/Contents/Resources/python/lib/"{libtcl*,libtk*,tcl*,tk*,itcl*,thread*} "$PYLIB/lib-dynload/_tkinter"*
find "$APP/Contents/Resources/python" -name '__pycache__' -type d -prune -exec rm -rf {} +
rm -f "$APP/Contents/Resources/python/EXTERNALLY-MANAGED" "$PYLIB/EXTERNALLY-MANAGED"

say "copy ro_pet"
rsync -a --exclude '__pycache__' --exclude '*.pyc' "$ROOT/ro_pet/" "$APP/Contents/Resources/lib/ro_pet/"

say "write launcher and Info.plist"
cat > "$APP/Contents/MacOS/ro-pet" <<'LAUNCH'
#!/bin/bash
# ro-pet.app launcher: runs `python -m ro_pet` with the bundled Python and prebuilt host.
DIR="$(cd "$(dirname "$0")/.." && pwd)"
export RO_PET_HOST="$DIR/MacOS/ro-pet-host"
export PYTHONPATH="$DIR/Resources/lib"
export PYTHONNOUSERSITE=1
export PYTHONUNBUFFERED=1
umask 077
mkdir -p "$HOME/.ro-pet"
exec "$DIR/Resources/python/bin/python3" -m ro_pet >>"$HOME/.ro-pet/pet.log" 2>&1
LAUNCH
chmod +x "$APP/Contents/MacOS/ro-pet"

cat > "$APP/Contents/Info.plist" <<PLIST
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
  <key>CFBundleName</key><string>ro pet</string>
  <key>CFBundleDisplayName</key><string>ro pet</string>
  <key>CFBundleIdentifier</key><string>bot.ro.pet</string>
  <key>CFBundleExecutable</key><string>ro-pet</string>
  <key>CFBundlePackageType</key><string>APPL</string>
  <key>CFBundleShortVersionString</key><string>${VERSION}</string>
  <key>CFBundleVersion</key><string>${VERSION}</string>
  <key>LSMinimumSystemVersion</key><string>13.0</string>
  <key>LSUIElement</key><true/>
  <key>NSHighResolutionCapable</key><true/>
</dict>
</plist>
PLIST

say "sign: ${IDENTITY/#-/ad-hoc(-)}"
SIGN_ARGS=(--force --sign "$IDENTITY")
if [ "$IDENTITY" != "-" ]; then
  ENT="$BUILD/entitlements.plist"
  cat > "$ENT" <<'ENT'
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0"><dict>
  <key>com.apple.security.cs.allow-jit</key><true/>
  <key>com.apple.security.cs.allow-unsigned-executable-memory</key><true/>
  <key>com.apple.security.cs.disable-library-validation</key><true/>
</dict></plist>
ENT
  SIGN_ARGS+=(--options runtime --timestamp --entitlements "$ENT")
fi
# sign inner Mach-O files first, the bundle last
while IFS= read -r f; do
  if file "$f" | grep -q 'Mach-O'; then codesign "${SIGN_ARGS[@]}" "$f" >/dev/null; fi
done < <(find "$APP/Contents" -type f ! -name 'Info.plist' ! -path '*/MacOS/ro-pet')
codesign "${SIGN_ARGS[@]}" "$APP" >/dev/null
codesign --verify --deep --strict "$APP" || die "signature verification failed"

du -sh "$APP" | awk '{print "app size: "$1}'
say "done: $APP (version $VERSION)"
