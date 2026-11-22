"""pro 라이선스 자동 받기(docs/SITE-PLAN.md '자동 활성화'). ro 안에서 외부로 연락하는 **유일한** 파일이다.

보내는 것: 이 Mac의 무작위 설치 토큰 하나(본문, POST). 파일·경로·이메일·기록은 보내지 않는다.
받는 것: 서명된 라이선스 키. 받은 키는 ro/license.py가 이 Mac에서 다시 서명을 검사한 뒤에만 저장한다.
연락하는 때: 사용자가 'Get pro…'로 결제를 시작한 뒤 잠시(구매 대기), 그리고 pro인 동안 하루 한 번(구독 갱신).
끄기: `auto(False)` → 연락하지 않는다(메일로 온 키를 붙여 넣는 방법은 그대로).
harden.network_offenders는 이 파일만 허용하고, 발급기 주소 한 곳만 쓰는지 따로 검사한다.
"""
import base64
import hashlib
import json
import os
import secrets
import time
import urllib.error
import urllib.request
from pathlib import Path

from . import config, license
from .fsutil import atomic_write

# 발급기(issuer/worker.js) 주소. 비어 있으면 자동 받기는 꺼진 것과 같다(도메인을 정하면 넣는다).
ISSUER = ""
PLANS = ("yearly", "monthly")
PENDING_SECONDS = 2 * 3600     # 결제를 시작하고 이만큼은 짧게 확인한다
PENDING_EVERY = 15             # 구매 대기 중 확인 간격(초)
DAILY = 86400


def _issuer():
    return (os.environ.get("RO_LICENSE_ISSUER") or ISSUER).rstrip("/")


def _home(home=None):
    return Path(home or config.HOME).expanduser()


def token(home=None):
    """이 Mac의 설치 토큰(32바이트 base64url). 없으면 만든다(0600). 개인정보는 들어 있지 않다."""
    path = _home(home) / "install-token"
    try:
        t = path.read_text(encoding="utf-8").strip()
        if len(t) == 43:
            return t
    except OSError:
        pass
    t = base64.urlsafe_b64encode(secrets.token_bytes(32)).rstrip(b"=").decode()
    atomic_write(path, t + "\n")
    return t


def install_hash(home=None):
    return hashlib.sha256(token(home).encode()).hexdigest()


def auto(on=None, home=None):
    """자동 받기 켜짐 여부. on을 주면 바꾼다. 기본은 켜짐(사용자 결정 2026-11-20 '완전 자동')."""
    off = _home(home) / "license-auto-off"
    if on is True and off.exists():
        off.unlink()
    elif on is False:
        atomic_write(off, "off\n")
    return not off.exists()


def active(home=None):
    return bool(_issuer()) and auto(home=home)


def buy_url(plan, home=None, now=None):
    """결제 시작 주소. 설치 토큰의 해시만 실어 보낸다. 구매 대기를 기록해 잠시 짧게 확인하게 한다."""
    if plan not in PLANS:
        raise ValueError("plan")
    if not _issuer():
        return None
    atomic_write(_home(home) / "license-pending", str(int(now if now is not None else time.time())) + "\n")
    return f"{_issuer()}/buy?plan={plan}&i={install_hash(home)}"


def pending(home=None, now=None):
    try:
        started = int((_home(home) / "license-pending").read_text().strip())
    except (OSError, ValueError):
        return False
    return 0 <= (now if now is not None else time.time()) - started < PENDING_SECONDS


def _post(url, body, timeout):
    req = urllib.request.Request(url, data=json.dumps(body).encode(), method="POST",
                                 headers={"Content-Type": "application/json", "User-Agent": "ro"})
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            return r.status, r.read(4096)
    except urllib.error.HTTPError as e:
        return e.code, b""
    except (OSError, ValueError):
        return None, b""


def fetch(home=None, timeout=10, post=_post):
    """발급기에서 이 Mac 몫의 최신 키를 받는다. 없거나 연락이 안 되면 None."""
    if not _issuer():
        return None
    status, raw = post(f"{_issuer()}/license", {"install": token(home)}, timeout)
    if status != 200:
        return None
    try:
        key = json.loads(raw).get("key")
    except (ValueError, AttributeError):
        return None
    return key if isinstance(key, str) else None


def due(home=None, now=None, edition="mini"):
    """지금 연락할 때인가: 구매 대기 중이면 PENDING_EVERY마다, pro면 하루 한 번, 그 밖엔 연락하지 않는다."""
    if not active(home):
        return False
    now = time.time() if now is None else now
    try:
        last = float((_home(home) / "license-checked").read_text().strip())
    except (OSError, ValueError):
        last = 0.0
    if pending(home, now):
        return now - last >= PENDING_EVERY
    return edition == "pro" and now - last >= DAILY


def sync(home=None, now=None, fetch=fetch):
    """한 번 받아 와 더 늦게 끝나는 유효한 키면 저장한다. 반환: 저장했으면 True."""
    now = time.time() if now is None else now
    atomic_write(_home(home) / "license-checked", f"{now}\n")
    key = fetch(home)
    if not key:
        return False
    try:
        new = license.parse(key, now=now)
    except license.LicenseError:
        return False
    current = license.status(home, now)
    if current["state"] == "valid" and current["exp"] >= new["exp"]:
        return False
    license.save(key, home, now=now)
    try:
        (_home(home) / "license-pending").unlink()   # 받았으면 구매 대기는 끝
    except FileNotFoundError:
        pass
    return True
