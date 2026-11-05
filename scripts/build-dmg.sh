#!/usr/bin/env bash
# Pack ro-pet.app into a DMG. Result: build/ro-pet-<version>.dmg
#   ./scripts/build-dmg.sh             build the app first, then the DMG
#   ./scripts/build-dmg.sh --no-app    only the DMG (build/ro-pet.app must exist)
#   NOTARY_PROFILE=ro-notary ./scripts/build-dmg.sh   also notarize and staple
# With SIGN_IDENTITY set the DMG is signed with the same certificate.
# Notarization needs a Developer ID signature and a keychain profile made once with:
#   xcrun notarytool store-credentials "ro-notary"
# (credentials live in the keychain, never in this repo)
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
BUILD="$ROOT/build"
APP="$BUILD/ro-pet.app"

say() { printf '\033[1m==>\033[0m %s\n' "$*"; }
die() { printf '\033[31merror:\033[0m %s\n' "$*" >&2; exit 1; }

[ "${1:-}" = "--no-app" ] || "$ROOT/scripts/build-app.sh"
[ -d "$APP" ] || die "$APP missing; run without --no-app"

VERSION="$(sed -n 's/^version = "\(.*\)"/\1/p' "$ROOT/pyproject.toml" | head -1)"
DMG="$BUILD/ro-pet-${VERSION:-dev}.dmg"
STAGE="$(mktemp -d "$BUILD/dmg-stage.XXXXXX")"
trap 'rm -rf "$STAGE"' EXIT

say "prepare DMG contents"
cp -R "$APP" "$STAGE/ro-pet.app"
ln -s /Applications "$STAGE/Applications"

say "create DMG: $DMG"
rm -f "$DMG"
hdiutil create -volname "ro pet" -srcfolder "$STAGE" -fs HFS+ -format UDZO -ov "$DMG" >/dev/null

if [ -n "${SIGN_IDENTITY:-}" ] && [ "$SIGN_IDENTITY" != "-" ]; then
  say "sign DMG"
  codesign --force --sign "$SIGN_IDENTITY" --timestamp "$DMG"
  if [ -n "${NOTARY_PROFILE:-}" ]; then
    say "notarize (waits for Apple)"
    xcrun notarytool submit "$DMG" --keychain-profile "$NOTARY_PROFILE" --wait
    xcrun stapler staple "$DMG"
  fi
elif [ -n "${NOTARY_PROFILE:-}" ]; then
  die "NOTARY_PROFILE needs SIGN_IDENTITY (Developer ID Application)"
fi

hdiutil verify "$DMG" >/dev/null || die "DMG verification failed"
du -sh "$DMG" | awk '{print "DMG size: "$1}'
say "done: $DMG"
