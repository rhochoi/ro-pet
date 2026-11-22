#!/usr/bin/env bash
# ro.app을 DMG로 묶는다. 결과: build/ro-<버전>.dmg
#   ./scripts/build-dmg.sh           앱을 먼저 빌드한 뒤 DMG 생성
#   ./scripts/build-dmg.sh --no-app  build/ro.app이 이미 있을 때 DMG만 생성
# 환경 변수:
#   SIGN_IDENTITY="Developer ID Application: 이름 (TEAMID)"  앱과 DMG를 이 인증서로 서명한다.
#                    비우면 ad-hoc이라 다른 Mac에서 Gatekeeper가 막는다(이 Mac·지인용).
#   APP_VERSION=0.3.0  배포 버전(앱 버전이자 파일 이름 ro-pet-0.3.0.dmg). 자동 업데이트는 이 숫자가 커져야 새 버전으로 본다.
#   NOTARY_PROFILE=<이름>  Apple 공증 + 스테이플까지 한다. 한 번만 만들어 둔다:
#                    xcrun notarytool store-credentials <이름> --apple-id … --team-id … (앱 암호는 키체인에만 저장)
#                    공증은 DMG를 Apple 서버로 보내므로, 배포할 때만 켠다.
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
BUILD="$ROOT/build"
APP="$BUILD/ro.app"

say() { printf '\033[1m==>\033[0m %s\n' "$*"; }
die() { printf '\033[31m오류:\033[0m %s\n' "$*" >&2; exit 1; }

[ "${1:-}" = "--no-app" ] || "$ROOT/scripts/build-app.sh"
[ -d "$APP" ] || die "$APP 이 없습니다. --no-app 없이 실행하세요."

VERSION="$(sed -n 's/^version = "\(.*\)"/\1/p' "$ROOT/pyproject.toml" | head -1)"
if [ -z "$VERSION" ]; then
  VERSION="$(cd "$ROOT" && git describe --tags --always 2>/dev/null | sed 's/^v//')"
fi
if [ -n "${APP_VERSION:-}" ]; then DMG="$BUILD/ro-pet-$APP_VERSION.dmg"  # 배포용: 릴리스 첨부 파일 이름과 같게
else DMG="$BUILD/ro-pet-${VERSION:-dev}.dmg"; fi
STAGE="$(mktemp -d "$BUILD/dmg-stage.XXXXXX")"
trap 'rm -rf "$STAGE"' EXIT

say "DMG 내용 준비"
cp -R "$APP" "$STAGE/ro.app"
ln -s /Applications "$STAGE/Applications"

say "DMG 생성: $DMG"
rm -f "$DMG"
hdiutil create -volname "ro" -srcfolder "$STAGE" -fs HFS+ -format UDZO -ov "$DMG" >/dev/null

if [ -n "${SIGN_IDENTITY:-}" ] && [ "$SIGN_IDENTITY" != "-" ]; then
  say "DMG 서명"
  codesign --force --sign "$SIGN_IDENTITY" --timestamp "$DMG"
fi

hdiutil verify "$DMG" >/dev/null || die "DMG 검증 실패"

if [ -n "${NOTARY_PROFILE:-}" ]; then
  { [ -n "${SIGN_IDENTITY:-}" ] && [ "$SIGN_IDENTITY" != "-" ]; } || die "공증은 Developer ID 서명(SIGN_IDENTITY)이 있어야 합니다."
  say "공증 제출(Apple 서버로 전송, 몇 분 걸린다)"
  xcrun notarytool submit "$DMG" --keychain-profile "$NOTARY_PROFILE" --wait || die "공증 실패. 'xcrun notarytool log <제출 ID> --keychain-profile $NOTARY_PROFILE'로 이유를 본다."
  say "스테이플"
  xcrun stapler staple "$DMG" || die "스테이플 실패"
  xcrun stapler validate "$DMG" || die "스테이플 검증 실패"
  say "Gatekeeper 평가"
  spctl --assess --type open --context context:primary-signature -v "$DMG" || die "Gatekeeper가 DMG를 거부했습니다."
elif [ -n "${SIGN_IDENTITY:-}" ] && [ "$SIGN_IDENTITY" != "-" ]; then
  say "서명만 했다. 내려받아 쓰는 사람의 Mac에서 열리려면 NOTARY_PROFILE로 공증까지 해야 한다."
else
  say "ad-hoc 서명이다. 다른 Mac에서는 Gatekeeper가 막는다(SIGN_IDENTITY·NOTARY_PROFILE 필요)."
fi
du -sh "$DMG" | awk '{print "DMG 크기: "$1}'
say "완료: $DMG"
