#!/usr/bin/env bash
# Build the standalone app. Result: build/ro.app
#
# Precompiles the Swift host and bundles a standalone Python (uv / python-build-standalone) plus ro_pet,
# so the user's Mac needs no Python and no swiftc. Then signs the bundle.
# Env: SIGN_IDENTITY="Developer ID Application: Name (TEAMID)"  distributable signature (hardened runtime).
#      empty -> ad-hoc signature (-): only for this Mac and friends (Gatekeeper warns elsewhere).
#      PYTHON_VERSION (default 3.13)
#      APP_VERSION=0.3.0  release version. Sparkle compares this number to decide whether an update is newer
#                         (always raise it; do not use a git describe value).
#      SU_FEED_URL=...    update list (appcast.xml) address. Default: the latest release of the ro-pet repository. Change only to test.
# Auto-update: downloads Sparkle (official release, SHA-256 pinned) into the bundle. See "Release" in the README.
# Apple Silicon (arm64) only for now.
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
BUILD="$ROOT/build"
APP="$BUILD/ro.app"
PYVER="${PYTHON_VERSION:-3.13}"
IDENTITY="${SIGN_IDENTITY:--}"
SPARKLE_VERSION=2.10.1
SPARKLE_SHA256=1a856d2a9edb8e628de88121d7be04cf0e2167f8641650b78fca00b14244cf27
SU_FEED_URL="${SU_FEED_URL:-https://github.com/rhochoi/ro-pet/releases/latest/download/appcast.xml}"
SU_PUBLIC_KEY="XcqWxjQ/xgHikxm0VUTYK2EqAXCoCjUYLN/TNpszLfE="  # public key; the private half lives only in the maintainer's keychain

say() { printf '\033[1m==>\033[0m %s\n' "$*"; }
die() { printf '\033[31merror:\033[0m %s\n' "$*" >&2; exit 1; }

[ "$(uname -s)" = Darwin ] || die "build on macOS only"
[ "$(uname -m)" = arm64 ] || die "Apple Silicon (arm64) only for now"
command -v swiftc >/dev/null || die "swiftc missing: xcode-select --install"
command -v uv >/dev/null || die "uv missing: https://astral.sh/uv"

VERSION="$(sed -n 's/^version = "\(.*\)"/\1/p' "$ROOT/pyproject.toml" | head -1)"
VERSION="${VERSION:-0.0.0}"
# CFBundleVersion allows only digits and dots
BUNDLE_VERSION="$(printf '%s' "$VERSION" | grep -oE '^[0-9]+(\.[0-9]+){0,2}' || echo 0.0.0)"
if [ -n "${APP_VERSION:-}" ]; then
  printf '%s' "$APP_VERSION" | grep -qE '^[0-9]+\.[0-9]+\.[0-9]+$' || die "APP_VERSION must be three numbers, like 0.3.0"
  BUNDLE_VERSION="$APP_VERSION"
fi

say "clean: $APP"
rm -rf "$APP"
mkdir -p "$APP/Contents/MacOS" "$APP/Contents/Resources/lib"

say "Sparkle $SPARKLE_VERSION (downloaded on first run only)"
SPK_CACHE="$BUILD/sparkle-cache/$SPARKLE_VERSION"
if [ ! -d "$SPK_CACHE/Sparkle.framework" ]; then
  mkdir -p "$SPK_CACHE"
  curl -fsSL -o "$SPK_CACHE.tar.xz" "https://github.com/sparkle-project/Sparkle/releases/download/$SPARKLE_VERSION/Sparkle-$SPARKLE_VERSION.tar.xz" || die "Sparkle download failed"
  [ "$(shasum -a 256 "$SPK_CACHE.tar.xz" | cut -d' ' -f1)" = "$SPARKLE_SHA256" ] || { rm -f "$SPK_CACHE.tar.xz"; die "Sparkle checksum mismatch; not using the download"; }
  tar -xf "$SPK_CACHE.tar.xz" -C "$SPK_CACHE"
fi

say "compile the Swift host"
# -target: match LSMinimumSystemVersion (13.0) in Info.plist so the binary is not tied to this Mac's newest macOS.
# Without it the build OS becomes the minimum version and the pet silently fails to appear on older macOS.
swiftc -O -target arm64-apple-macos13.0 -F "$SPK_CACHE" "$ROOT/ro_pet/pet_mac.swift" -o "$APP/Contents/MacOS/ro-pet-host" \
  -framework AppKit -framework WebKit -framework Sparkle \
  -Xlinker -rpath -Xlinker @executable_path/../Frameworks
MINOS="$(vtool -show-build "$APP/Contents/MacOS/ro-pet-host" | awk '/minos/{print $2; exit}')"
[ "${MINOS%%.*}" -le 13 ] || die "the host's minimum macOS is $MINOS (must be 13 or lower)"

say "standalone Python $PYVER (uv, downloaded on first run)"
PYCACHE="$BUILD/python-cache"
uv python install "$PYVER" --install-dir "$PYCACHE" >/dev/null
PYSRC="$(find "$PYCACHE" -maxdepth 1 -type d -name "cpython-$PYVER*" | head -1)"
[ -n "$PYSRC" ] || die "standalone Python not found in $PYCACHE"
# follow the symlink (3.13 -> real folder) and copy the real contents
cp -RL "$PYSRC" "$APP/Contents/Resources/python"
PYLIB="$APP/Contents/Resources/python/lib/python$PYVER"
# drop big folders the app does not need
rm -rf "$PYLIB/test" "$PYLIB/idlelib" "$PYLIB/turtledemo" "$PYLIB/tkinter" \
       "$PYLIB/ensurepip" "$PYLIB/site-packages/pip"* "$APP/Contents/Resources/python/share"
rm -rf "$APP/Contents/Resources/python/lib/"{libtcl*,libtk*,tcl*,tk*,itcl*,thread*} "$PYLIB/lib-dynload/_tkinter"*
find "$APP/Contents/Resources/python" -name '__pycache__' -type d -prune -exec rm -rf {} +
rm -f "$APP/Contents/Resources/python/EXTERNALLY-MANAGED" "$PYLIB/EXTERNALLY-MANAGED"

say "copy ro_pet"
rsync -a --exclude '__pycache__' --exclude '*.pyc' "$ROOT/ro_pet/" "$APP/Contents/Resources/lib/ro_pet/"

say "precompile bytecode (before signing)"
# A __pycache__ created at run time breaks the signature seal (codesign --verify fails, update checks wobble).
# So compile now, sign it in, and let the launcher use PYTHONDONTWRITEBYTECODE. Hash-based, so file times do not matter.
"$APP/Contents/Resources/python/bin/python3" -m compileall -q -j 0 --invalidation-mode unchecked-hash "$APP/Contents/Resources/lib" "$PYLIB" >/dev/null

say "copy the Sparkle framework"
mkdir -p "$APP/Contents/Frameworks"
ditto "$SPK_CACHE/Sparkle.framework" "$APP/Contents/Frameworks/Sparkle.framework"
# not a sandboxed app, so the XPC services are unnecessary (Sparkle docs); fewer things to sign
rm -rf "$APP/Contents/Frameworks/Sparkle.framework/Versions/B/XPCServices" "$APP/Contents/Frameworks/Sparkle.framework/XPCServices"

say "copy the app icon"
cp "$ROOT/assets/icon/ro.icns" "$APP/Contents/Resources/ro.icns"

say "write launcher and Info.plist"
cat > "$APP/Contents/MacOS/ro" <<'LAUNCH'
#!/bin/bash
# ro.app launcher: runs `python -m ro_pet` with the bundled Python and prebuilt host.
DIR="$(cd "$(dirname "$0")/.." && pwd)"
export RO_PET_HOST="$DIR/MacOS/ro-pet-host"
export PYTHONPATH="$DIR/Resources/lib"
export PYTHONNOUSERSITE=1
export PYTHONDONTWRITEBYTECODE=1  # never write files inside the signed bundle
export PYTHONUNBUFFERED=1
umask 077
mkdir -p "$HOME/.ro-pet"
exec "$DIR/Resources/python/bin/python3" -m ro_pet >>"$HOME/.ro-pet/pet.log" 2>&1
LAUNCH
chmod +x "$APP/Contents/MacOS/ro"

cat > "$APP/Contents/Info.plist" <<PLIST
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
  <key>CFBundleName</key><string>ro</string>
  <key>CFBundleDisplayName</key><string>ro</string>
  <key>CFBundleIdentifier</key><string>bot.ro.app</string>
  <key>CFBundleExecutable</key><string>ro</string>
  <key>CFBundleIconFile</key><string>ro</string>
  <key>SUFeedURL</key><string>${SU_FEED_URL}</string>
  <key>SUPublicEDKey</key><string>${SU_PUBLIC_KEY}</string>
  <key>SUEnableAutomaticChecks</key><true/>
  <key>SUSendProfileInfo</key><false/>
  <key>SUAutomaticallyUpdate</key><true/>
  <key>SUScheduledCheckInterval</key><integer>86400</integer>
  <key>CFBundlePackageType</key><string>APPL</string>
  <key>CFBundleShortVersionString</key><string>${BUNDLE_VERSION}</string>
  <key>CFBundleVersion</key><string>${BUNDLE_VERSION}</string>
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
# sign inner Mach-O files first (.so, .dylib, executables), the bundle last
while IFS= read -r f; do
  if file "$f" | grep -q 'Mach-O'; then codesign "${SIGN_ARGS[@]}" "$f" >/dev/null; fi
done < <(find "$APP/Contents" -type f ! -name 'Info.plist' ! -path '*/MacOS/ro' ! -path '*/Frameworks/Sparkle.framework/*')
# Sparkle is signed per bundle (Updater.app, then the framework), innermost first, so the seals match
SPK_B="$APP/Contents/Frameworks/Sparkle.framework/Versions/B"
codesign "${SIGN_ARGS[@]}" "$SPK_B/Autoupdate" >/dev/null
codesign "${SIGN_ARGS[@]}" "$SPK_B/Updater.app" >/dev/null
codesign "${SIGN_ARGS[@]}" "$APP/Contents/Frameworks/Sparkle.framework" >/dev/null
codesign "${SIGN_ARGS[@]}" "$APP" >/dev/null
codesign --verify --deep --strict "$APP" || die "signature verification failed"

du -sh "$APP" | awk '{print "app size: "$1}'
say "done: $APP (version $VERSION)"
