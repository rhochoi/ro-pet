#!/usr/bin/env bash
# ro.app(독립 실행 앱) 빌드. 결과: build/ro.app
#   ./scripts/build-app.sh
# 하는 일: 펫 화면(Swift)을 미리 컴파일 → 독립 Python 런타임(uv가 받는 python-build-standalone)과 ro 패키지를 번들에 복사
#          → 서명. 사용자 Mac에 Python·swiftc·ro가 없어도 실행된다(엔진 CLI(claude 등)는 사용자가 따로 설치·로그인).
# 환경 변수: SIGN_IDENTITY="Developer ID Application: 이름 (TEAMID)" 이면 배포용 서명(hardened runtime).
#            비우면 ad-hoc 서명(-)이라 이 Mac과 지인용으로만 쓴다.
#            PYTHON_VERSION(기본 3.13)
#            APP_VERSION=0.3.0  배포 버전. Sparkle은 이 숫자의 크기로 새 버전인지 정한다(꼭 이전보다 크게, git describe 값은 쓰지 않는다).
#            SU_FEED_URL=…      업데이트 목록(appcast.xml) 주소. 기본은 ro-pet 저장소의 최신 릴리스. 시험할 때만 바꾼다.
# 자동 업데이트: Sparkle(공식 릴리스, SHA-256 고정)을 내려받아 번들에 넣는다. 만드는 법은 README의 "릴리스" 절.
# 현재는 Apple Silicon(arm64) 전용이다.
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
BUILD="$ROOT/build"
APP="$BUILD/ro.app"
PYVER="${PYTHON_VERSION:-3.13}"
IDENTITY="${SIGN_IDENTITY:--}"
SPARKLE_VERSION=2.10.1
SPARKLE_SHA256=1a856d2a9edb8e628de88121d7be04cf0e2167f8641650b78fca00b14244cf27
SU_FEED_URL="${SU_FEED_URL:-https://github.com/rhochoi/ro-pet/releases/latest/download/appcast.xml}"
SU_PUBLIC_KEY="XcqWxjQ/xgHikxm0VUTYK2EqAXCoCjUYLN/TNpszLfE="  # 공개 키. 짝인 개인 키는 만든 사람의 키체인에만 있다

say() { printf '\033[1m==>\033[0m %s\n' "$*"; }
die() { printf '\033[31m오류:\033[0m %s\n' "$*" >&2; exit 1; }

[ "$(uname -s)" = Darwin ] || die "macOS에서만 빌드합니다."
[ "$(uname -m)" = arm64 ] || die "지금은 Apple Silicon(arm64)만 지원합니다."
command -v swiftc >/dev/null || die "swiftc가 없습니다: xcode-select --install"
command -v uv >/dev/null || die "uv가 없습니다: https://astral.sh/uv"

VERSION="$(sed -n 's/^version = "\(.*\)"/\1/p' "$ROOT/pyproject.toml" | head -1)"
if [ -z "$VERSION" ]; then
  VERSION="$(cd "$ROOT" && git describe --tags --always 2>/dev/null | sed 's/^v//')"
fi
VERSION="${VERSION:-0.0.0}"
# CFBundleVersion은 숫자와 점만 허용하므로 앞 세 마디만 쓴다
BUNDLE_VERSION="$(printf '%s' "$VERSION" | grep -oE '^[0-9]+(\.[0-9]+){0,2}' || echo 0.0.0)"
if [ -n "${APP_VERSION:-}" ]; then
  printf '%s' "$APP_VERSION" | grep -qE '^[0-9]+\.[0-9]+\.[0-9]+$' || die "APP_VERSION은 0.3.0처럼 숫자 세 마디여야 합니다."
  BUNDLE_VERSION="$APP_VERSION"
fi
if [ -n "${RO_LICENSE_ISSUER:-}" ]; then
  printf '%s' "$RO_LICENSE_ISSUER" | grep -qE '^https://[^[:space:]"'"'"']+$' || die "RO_LICENSE_ISSUER는 https:// 주소여야 합니다."
fi

say "정리: $APP"
rm -rf "$APP"
mkdir -p "$APP/Contents/MacOS" "$APP/Contents/Resources/lib"

say "Sparkle $SPARKLE_VERSION 준비(첫 실행에만 내려받음)"
SPK_CACHE="$BUILD/sparkle-cache/$SPARKLE_VERSION"
if [ ! -d "$SPK_CACHE/Sparkle.framework" ]; then
  mkdir -p "$SPK_CACHE"
  curl -fsSL -o "$SPK_CACHE.tar.xz" "https://github.com/sparkle-project/Sparkle/releases/download/$SPARKLE_VERSION/Sparkle-$SPARKLE_VERSION.tar.xz" || die "Sparkle 다운로드 실패"
  [ "$(shasum -a 256 "$SPK_CACHE.tar.xz" | cut -d' ' -f1)" = "$SPARKLE_SHA256" ] || { rm -f "$SPK_CACHE.tar.xz"; die "Sparkle 체크섬이 다릅니다. 받은 파일을 쓰지 않습니다."; }
  tar -xf "$SPK_CACHE.tar.xz" -C "$SPK_CACHE"
fi

say "펫 화면 컴파일(Swift)"
# -target: 이 Mac의 최신 macOS 전용 바이너리가 되지 않게 Info.plist의 LSMinimumSystemVersion(13.0)에 맞춘다.
# 빼면 빌드한 OS 버전이 최소 버전으로 박혀, 더 낮은 macOS에서는 펫 화면이 말없이 뜨지 않는다.
swiftc -O -target arm64-apple-macos13.0 -F "$SPK_CACHE" "$ROOT/ro/pet_mac.swift" -o "$APP/Contents/MacOS/ro-pet-host" \
  -framework AppKit -framework WebKit -framework Carbon -framework IOKit -framework CoreAudio -framework AVFoundation \
  -framework Sparkle \
  -Xlinker -rpath -Xlinker @executable_path/../Frameworks
MINOS="$(vtool -show-build "$APP/Contents/MacOS/ro-pet-host" | awk '/minos/{print $2; exit}')"
[ "${MINOS%%.*}" -le 13 ] || die "펫 화면의 최소 macOS가 $MINOS 입니다(13 이하여야 함)."

say "Vision OCR 헬퍼 컴파일(Swift)"
swiftc -O -target arm64-apple-macos13.0 "$ROOT/ro/ocr_mac.swift" -o "$APP/Contents/MacOS/ro-ocr" \
  -framework Vision -framework PDFKit -framework AppKit
OCR_MINOS="$(vtool -show-build "$APP/Contents/MacOS/ro-ocr" | awk '/minos/{print $2; exit}')"
[ "${OCR_MINOS%%.*}" -le 13 ] || die "OCR 헬퍼의 최소 macOS가 $OCR_MINOS 입니다(13 이하여야 함)."

say "독립 Python $PYVER 준비(uv, 첫 실행에만 내려받음)"
PYCACHE="$BUILD/python-cache"
uv python install "$PYVER" --install-dir "$PYCACHE" >/dev/null
PYSRC="$(find "$PYCACHE" -maxdepth 1 -type d -name "cpython-$PYVER*" | head -1)"
[ -n "$PYSRC" ] || die "독립 Python을 찾지 못했습니다: $PYCACHE"
# 심볼릭 링크(3.13 → 실제 폴더)는 따라가서 실제 내용을 복사한다
cp -RL "$PYSRC" "$APP/Contents/Resources/python"
PYLIB="$APP/Contents/Resources/python/lib/python$PYVER"
# 실행에 필요 없는 큰 폴더를 덜어낸다
rm -rf "$PYLIB/test" "$PYLIB/idlelib" "$PYLIB/turtledemo" "$PYLIB/tkinter" \
       "$PYLIB/ensurepip" "$PYLIB/site-packages/pip"* "$APP/Contents/Resources/python/share"
rm -rf "$APP/Contents/Resources/python/lib/"{libtcl*,libtk*,tcl*,tk*,itcl*,thread*} "$PYLIB/lib-dynload/_tkinter"*
find "$APP/Contents/Resources/python" -name '__pycache__' -type d -prune -exec rm -rf {} +
rm -f "$APP/Contents/Resources/python/EXTERNALLY-MANAGED" "$PYLIB/EXTERNALLY-MANAGED"

say "ro 패키지 복사(개인 설정·테스트 제외)"
rsync -a --exclude '__pycache__' --exclude '*.pyc' "$ROOT/ro/" "$APP/Contents/Resources/lib/ro/"

say "바이트코드 미리 만들기(서명 전에)"
# 실행 중 __pycache__가 번들에 생기면 서명 봉인이 깨진다(codesign --verify 실패, 업데이트 검증도 흔들린다).
# 그래서 미리 만들어 서명에 포함하고, 런처는 PYTHONDONTWRITEBYTECODE로 새로 쓰지 않는다. 해시 방식이라 파일 시각이 바뀌어도 유효하다.
"$APP/Contents/Resources/python/bin/python3" -m compileall -q -j 0 --invalidation-mode unchecked-hash "$APP/Contents/Resources/lib" "$PYLIB" >/dev/null

say "Sparkle 프레임워크 복사"
mkdir -p "$APP/Contents/Frameworks"
ditto "$SPK_CACHE/Sparkle.framework" "$APP/Contents/Frameworks/Sparkle.framework"
# 샌드박스 앱이 아니라서 XPC 서비스는 필요 없다(Sparkle 문서). 서명할 대상도 줄어든다.
rm -rf "$APP/Contents/Frameworks/Sparkle.framework/Versions/B/XPCServices" "$APP/Contents/Frameworks/Sparkle.framework/XPCServices"

say "앱 아이콘 복사"
cp "$ROOT/assets/icon/ro.icns" "$APP/Contents/Resources/ro.icns"

say "실행 스크립트·Info.plist 작성"
cat > "$APP/Contents/MacOS/ro" <<'LAUNCH'
#!/bin/bash
# ro.app 실행기: 번들 Python으로 `ro pet`을 띄운다. Finder 실행은 PATH가 좁아서 흔한 CLI 위치를 더한다.
DIR="$(cd "$(dirname "$0")/.." && pwd)"
export PATH="$HOME/.local/bin:$HOME/.claude/local:/opt/homebrew/bin:/usr/local/bin:$HOME/.npm-global/bin:$PATH"
export RO_PET_HOST="$DIR/MacOS/ro-pet-host"
export RO_OCR_BIN="$DIR/MacOS/ro-ocr"
export PYTHONPATH="$DIR/Resources/lib"
export RO_EDITION=mini  # 기본은 꾸미기. 환경 변수로 pro가 켜지지 않게 덮어쓴다
export RO_EDITION_SOURCE=license  # 유효한 라이선스 키(~/.ro/license)가 있을 때만 ro가 pro로 바꾼다(ro/license.py)
export PYTHONNOUSERSITE=1
export PYTHONSAFEPATH=1  # 현재 폴더의 ro/를 불러오지 않는다(터미널에서 저장소 안에서 띄우면 개발 코드가 돌았다)
export PYTHONDONTWRITEBYTECODE=1  # 서명된 번들 안에 파일을 만들지 않는다
export PYTHONUNBUFFERED=1
umask 077
mkdir -p "$HOME/.ro"
exec "$DIR/Resources/python/bin/python3" -m ro pet >>"$HOME/.ro/pet.log" 2>&1
LAUNCH
if [ -n "${RO_LICENSE_ISSUER:-}" ]; then
  # 빌드 시 지정한 발급기 주소를 실행기에 주입한다(exec 직전)
  python3 - "$APP/Contents/MacOS/ro" "$RO_LICENSE_ISSUER" <<'PY'
import sys
from pathlib import Path
p = Path(sys.argv[1])
issuer = sys.argv[2]
txt = p.read_text(encoding="utf-8")
line = f'export RO_LICENSE_ISSUER="{issuer}"\n'
p.write_text(txt.replace("umask 077\n", line + "umask 077\n", 1), encoding="utf-8")
PY
fi
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

say "서명: ${IDENTITY/#-/ad-hoc(-)}"
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
# 안쪽(.so·.dylib·실행 파일)부터 서명하고 마지막에 번들 전체를 서명한다
while IFS= read -r f; do
  if file "$f" | grep -q 'Mach-O'; then codesign "${SIGN_ARGS[@]}" "$f" >/dev/null; fi
done < <(find "$APP/Contents" -type f ! -name 'Info.plist' ! -path '*/MacOS/ro' ! -path '*/Frameworks/Sparkle.framework/*')
# Sparkle은 번들(Updater.app·프레임워크) 단위로, 안쪽부터 서명해야 봉인이 맞는다
SPK_B="$APP/Contents/Frameworks/Sparkle.framework/Versions/B"
codesign "${SIGN_ARGS[@]}" "$SPK_B/Autoupdate" >/dev/null
codesign "${SIGN_ARGS[@]}" "$SPK_B/Updater.app" >/dev/null
codesign "${SIGN_ARGS[@]}" "$APP/Contents/Frameworks/Sparkle.framework" >/dev/null
codesign "${SIGN_ARGS[@]}" "$APP" >/dev/null
codesign --verify --deep --strict "$APP" || die "서명 검증 실패"

du -sh "$APP" | awk '{print "앱 크기: "$1}'
say "완료: $APP (버전 $VERSION)"
