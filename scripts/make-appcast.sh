#!/usr/bin/env bash
# 업데이트 목록(appcast.xml)을 만든다. 결과: build/appcast.xml
#   ./scripts/make-appcast.sh build/ro-pet-0.3.0.dmg
# DMG는 build-dmg.sh가 공증·스테이플까지 끝낸 최종 파일이어야 한다(서명은 파일 바이트에 걸리므로 만든 뒤 고치면 안 된다).
# 파일 이름의 버전(ro-pet-<버전>.dmg)이 곧 릴리스 태그(v<버전>)와 다운로드 주소가 된다.
# 업데이트 서명 개인 키는 만든 사람의 키체인에 있다(Sparkle sign_update가 읽는다). 이 스크립트는 키를 출력하지 않는다.
# 환경 변수: RELEASE_REPO(기본 rhochoi/ro-pet), DOWNLOAD_PREFIX(시험용: 다운로드 주소 앞부분을 바꾼다)
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
BUILD="$ROOT/build"
SPARKLE_VERSION=2.10.1
REPO="${RELEASE_REPO:-rhochoi/ro-pet}"

die() { printf '\033[31m오류:\033[0m %s\n' "$*" >&2; exit 1; }

DMG="${1:-}"
[ -f "$DMG" ] || die "사용법: $0 build/ro-pet-<버전>.dmg"
NAME="$(basename "$DMG")"
VER="$(printf '%s' "$NAME" | sed -nE 's/^ro-pet-([0-9]+\.[0-9]+\.[0-9]+)\.dmg$/\1/p')"
[ -n "$VER" ] || die "파일 이름이 ro-pet-0.3.0.dmg 꼴이어야 합니다: $NAME"
SIGN="$BUILD/sparkle-cache/$SPARKLE_VERSION/bin/sign_update"
[ -x "$SIGN" ] || die "$SIGN 이 없습니다. 먼저 ./scripts/build-app.sh 를 한 번 실행하세요."

# 스테이플이 끝난 DMG인지(서명 뒤에 바꾼 파일을 올리지 않게)
xcrun stapler validate "$DMG" >/dev/null 2>&1 || printf '\033[33m주의:\033[0m 스테이플되지 않은 DMG입니다(시험용이 아니면 공증부터 하세요).\n' >&2

ATTRS="$("$SIGN" "$DMG")"   # sparkle:edSignature="…" length="…"
case "$ATTRS" in *edSignature=*length=*) ;; *) die "서명을 만들지 못했습니다. 키체인에 업데이트 서명 키가 있나요?";; esac
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
xmllint --noout "$BUILD/appcast.xml" || die "appcast.xml이 올바른 XML이 아닙니다."
echo "완료: $BUILD/appcast.xml (버전 $VER)"
