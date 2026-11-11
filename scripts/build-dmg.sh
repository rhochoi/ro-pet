#!/usr/bin/env bash
# Pack ro.app into a DMG. Result: build/ro-pet-<version>.dmg
#   ./scripts/build-dmg.sh             build the app first, then the DMG
#   ./scripts/build-dmg.sh --no-app    only the DMG (build/ro.app must exist)
# Env:
#   SIGN_IDENTITY="Developer ID Application: Name (TEAMID)"  sign the app and the DMG with this certificate.
#                    Empty -> ad-hoc, which Gatekeeper blocks on other Macs (this Mac and friends only).
#   APP_VERSION=0.3.0  release version (the app version and the file name ro-pet-0.3.0.dmg).
#                    Auto-update treats a bigger number as a new version.
#   NOTARY_PROFILE=<name>  also notarize with Apple and staple. Create the profile once:
#                    xcrun notarytool store-credentials <name> --apple-id ... --team-id ... (the app password stays in the keychain)
#                    Notarization uploads the DMG to Apple, so turn it on only for releases.
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
BUILD="$ROOT/build"
APP="$BUILD/ro.app"
STAGE="$BUILD/dmg-stage"

say() { printf '\033[1m==>\033[0m %s\n' "$*"; }
die() { printf '\033[31merror:\033[0m %s\n' "$*" >&2; exit 1; }

[ "${1:-}" = "--no-app" ] || "$ROOT/scripts/build-app.sh"
[ -d "$APP" ] || die "$APP missing; run without --no-app"

VERSION="$(sed -n 's/^version = "\(.*\)"/\1/p' "$ROOT/pyproject.toml" | head -1)"
if [ -n "${APP_VERSION:-}" ]; then DMG="$BUILD/ro-pet-$APP_VERSION.dmg"  # release: same name as the release asset
else DMG="$BUILD/ro-pet-${VERSION:-dev}.dmg"; fi

rm -rf "$STAGE" "$DMG"
mkdir -p "$STAGE"
say "prepare DMG contents"
cp -R "$APP" "$STAGE/ro.app"
ln -s /Applications "$STAGE/Applications"

say "create DMG: $DMG"
hdiutil create -volname "ro" -srcfolder "$STAGE" -fs HFS+ -format UDZO -ov "$DMG" >/dev/null
rm -rf "$STAGE"
if [ -n "${SIGN_IDENTITY:-}" ] && [ "$SIGN_IDENTITY" != "-" ]; then
  say "sign DMG"
  codesign --force --sign "$SIGN_IDENTITY" --timestamp "$DMG" >/dev/null
fi
hdiutil verify "$DMG" >/dev/null || die "DMG verification failed"

if [ -n "${NOTARY_PROFILE:-}" ]; then
  { [ -n "${SIGN_IDENTITY:-}" ] && [ "$SIGN_IDENTITY" != "-" ]; } || die "notarization needs a Developer ID signature (SIGN_IDENTITY)"
  say "submit for notarization (uploads to Apple, takes a few minutes)"
  xcrun notarytool submit "$DMG" --keychain-profile "$NOTARY_PROFILE" --wait || die "notarization failed; see why with: xcrun notarytool log <submission id> --keychain-profile $NOTARY_PROFILE"
  say "staple"
  xcrun stapler staple "$DMG" || die "stapling failed"
  xcrun stapler validate "$DMG" || die "staple validation failed"
  say "Gatekeeper assessment"
  spctl --assess --type open --context context:primary-signature -v "$DMG" || die "Gatekeeper rejected the DMG"
elif [ -n "${SIGN_IDENTITY:-}" ] && [ "$SIGN_IDENTITY" != "-" ]; then
  say "signed only. People who download it need NOTARY_PROFILE (notarization) to open it on their Mac."
else
  say "ad-hoc signed. Gatekeeper blocks it on other Macs (needs SIGN_IDENTITY and NOTARY_PROFILE)."
fi
du -sh "$DMG" | awk '{print "DMG size: "$1}'
say "done: $DMG"
