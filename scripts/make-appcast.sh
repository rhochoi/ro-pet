#!/usr/bin/env bash
# Make the update list (appcast.xml). Result: build/appcast.xml
#   ./scripts/make-appcast.sh build/ro-pet-0.3.0.dmg
# The DMG must be the final one that build-dmg.sh already notarized and stapled (the signature covers the file bytes, so never edit it afterwards).
# The version in the file name (ro-pet-<version>.dmg) becomes the release tag (v<version>) and the download address.
# The update-signing private key lives in the maintainer's keychain (Sparkle's sign_update reads it). This script never prints the key.
# Env: RELEASE_REPO (default rhochoi/ro-pet), DOWNLOAD_PREFIX (for tests: replaces the start of the download address)
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
BUILD="$ROOT/build"
SPARKLE_VERSION=2.10.1
REPO="${RELEASE_REPO:-rhochoi/ro-pet}"

die() { printf '\033[31merror:\033[0m %s\n' "$*" >&2; exit 1; }

DMG="${1:-}"
[ -f "$DMG" ] || die "usage: $0 build/ro-pet-<version>.dmg"
NAME="$(basename "$DMG")"
VER="$(printf '%s' "$NAME" | sed -nE 's/^ro-pet-([0-9]+\.[0-9]+\.[0-9]+)\.dmg$/\1/p')"
[ -n "$VER" ] || die "the file name must look like ro-pet-0.3.0.dmg: $NAME"
SIGN="$BUILD/sparkle-cache/$SPARKLE_VERSION/bin/sign_update"
[ -x "$SIGN" ] || die "$SIGN is missing. Run ./scripts/build-app.sh once first."

# is it the stapled DMG? (do not publish a file changed after signing)
xcrun stapler validate "$DMG" >/dev/null 2>&1 || printf '\033[33mwarning:\033[0m this DMG is not stapled (notarize first unless this is a test).\n' >&2

ATTRS="$("$SIGN" "$DMG")"   # sparkle:edSignature="..." length="..."
case "$ATTRS" in *edSignature=*length=*) ;; *) die "could not sign. Is the update-signing key in the keychain?";; esac
URL="${DOWNLOAD_PREFIX:-https://github.com/$REPO/releases/download/v$VER}/$NAME"
DATE="$(LC_ALL=C date -u '+%a, %d %b %Y %H:%M:%S +0000')"

cat > "$BUILD/appcast.xml" <<XML
<?xml version="1.0" encoding="utf-8"?>
<rss version="2.0" xmlns:sparkle="http://www.andymatuschak.org/xml-namespaces/sparkle">
  <channel>
    <title>ro pet</title>
    <item>
      <title>Version $VER</title>
      <pubDate>$DATE</pubDate>
      <sparkle:version>$VER</sparkle:version>
      <sparkle:shortVersionString>$VER</sparkle:shortVersionString>
      <sparkle:minimumSystemVersion>13.0</sparkle:minimumSystemVersion>
      <enclosure url="$URL" $ATTRS type="application/octet-stream"/>
    </item>
  </channel>
</rss>
XML
xmllint --noout "$BUILD/appcast.xml" || die "appcast.xml is not valid XML"
echo "done: $BUILD/appcast.xml (version $VER)"
