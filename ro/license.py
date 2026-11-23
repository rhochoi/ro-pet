"""ro pro 라이선스: 오프라인 서명 검사. 네트워크를 쓰지 않는다(docs/SITE-PLAN.md '구독 + 오프라인 키 설계').

키 형식: RO1.<payload>.<signature>  (둘 다 base64url, 패딩 없음)
  payload = JSON {"v":1, "kid":공개 키 ID, "id":라이선스 ID, "plan":"pro", "iat":발급 시각, "exp":만료 시각(유닉스 초)}
  signature = Ed25519(_DOMAIN + payload 바이트)

이 검사는 정직한 사용자용 잠금이다. 앱에 소스가 들어 있어 고치면 우회할 수 있다(기획서 '위험').
만료돼도 사용자 파일·기록은 건드리지 않고, 에디션만 mini로 돌아간다.
"""
import base64
import binascii
import json
import os
import time
from pathlib import Path

from . import _ed25519, config
from .fsutil import atomic_write

PREFIX = "RO1"
_DOMAIN = b"ro-license-v1\n"
MAX_KEY_LEN = 2048

# 운영 공개 키(kid → 32바이트 공개 키 hex). 짝인 개인 키는 발급하는 쪽에만 있다(저장소·로그 금지, 원칙 2).
# 키를 바꿀 땐 새 kid를 더하고 옛 kid는 그 키들이 다 만료될 때까지 남긴다. 키 만들기: scripts/license-tool.py keygen
PUBLIC_KEYS = {
    "ro1": "f8e63001120039f03be632d6d634b72a6a58eb62134338b408cc252ae360053f",  # 운영 1번 키(2026-11-20 생성, 시드는 발급자만)
}


class LicenseError(ValueError):
    pass


def _b64d(s):
    try:
        return base64.urlsafe_b64decode(s + "=" * (-len(s) % 4))
    except (binascii.Error, ValueError):
        raise LicenseError("키 형식이 올바르지 않습니다.") from None


def _b64e(b):
    return base64.urlsafe_b64encode(b).rstrip(b"=").decode()


def encode(payload, seed):
    """발급 도구·테스트용: payload(dict)에 서명해 키 문자열을 만든다."""
    body = json.dumps(payload, separators=(",", ":"), sort_keys=True).encode()
    return f"{PREFIX}.{_b64e(body)}.{_b64e(_ed25519.sign(seed, _DOMAIN + body))}"


def parse(key, now=None, keys=None):
    """키를 검사해 payload(dict)를 돌려준다. 문제가 있으면 LicenseError(사용자에게 보여 줄 문장)."""
    keys = PUBLIC_KEYS if keys is None else keys
    key = (key or "").strip()
    if not key:
        raise LicenseError("키가 비어 있습니다.")
    if len(key) > MAX_KEY_LEN:
        raise LicenseError("키가 너무 깁니다.")
    parts = key.split(".")
    if len(parts) != 3 or parts[0] != PREFIX:
        raise LicenseError("ro 라이선스 키가 아닙니다.")
    body, sig = _b64d(parts[1]), _b64d(parts[2])
    try:
        payload = json.loads(body)
    except (UnicodeDecodeError, ValueError):
        raise LicenseError("키 형식이 올바르지 않습니다.") from None
    if not isinstance(payload, dict) or payload.get("v") != 1:
        raise LicenseError("지원하지 않는 키 버전입니다. ro를 업데이트해 보세요.")
    pub_hex = keys.get(payload.get("kid")) if isinstance(payload.get("kid"), str) else None
    if not pub_hex:
        raise LicenseError("이 버전의 ro가 알지 못하는 키입니다. ro를 업데이트해 보세요.")
    if not _ed25519.verify(bytes.fromhex(pub_hex), _DOMAIN + body, sig):
        raise LicenseError("키 서명이 맞지 않습니다. 받은 키를 그대로 붙여 넣었는지 확인하세요.")
    exp = payload.get("exp")
    if payload.get("plan") != "pro" or not isinstance(exp, int) or isinstance(exp, bool):
        raise LicenseError("키 내용이 올바르지 않습니다.")
    if exp <= (time.time() if now is None else now):
        raise LicenseError(f"키가 {_date(exp)}에 만료됐습니다. 구독을 갱신하면 새 키가 이메일로 옵니다.")
    return payload


def _date(ts):
    return time.strftime("%Y-%m-%d", time.localtime(ts))


def _path(home=None):
    return Path(home or config.HOME).expanduser() / "license"


def load(home=None):
    try:
        return _path(home).read_text(encoding="utf-8")[:MAX_KEY_LEN + 1]
    except (OSError, UnicodeDecodeError):
        return None


def save(key, home=None, now=None):
    """유효한 키만 저장한다(0600). 틀리면 LicenseError, 기존 키는 그대로."""
    payload = parse(key, now=now)
    atomic_write(_path(home), key.strip() + "\n")
    return payload


def remove(home=None):
    """키 파일만 지운다. 돌려주는 값: 지웠으면 True."""
    try:
        os.unlink(_path(home))
        return True
    except FileNotFoundError:
        return False


def status(home=None, now=None):
    """{"state": "none"|"valid"|"invalid", "exp": 유닉스 초|None, "id": str|None, "message": str}"""
    key = load(home)
    if key is None:
        return {"state": "none", "exp": None, "id": None, "message": "라이선스 키가 없습니다(mini)."}
    try:
        p = parse(key, now=now)
    except LicenseError as exc:
        return {"state": "invalid", "exp": None, "id": None, "message": str(exc)}
    return {"state": "valid", "exp": p["exp"], "id": p.get("id"), "message": f"pro 사용 중 · {_date(p['exp'])}까지"}


def edition(home=None, now=None):
    """유효한 키가 있으면 "pro", 그 밖의 모든 경우(오류 포함) "mini"."""
    try:
        return "pro" if status(home, now)["state"] == "valid" else "mini"
    except Exception:  # 잠금 판단이 앱 실행을 막지 않는다
        return "mini"


def apply_edition_from_license():
    """번들 앱 실행기(RO_EDITION_SOURCE=license)에서만: 환경 변수 대신 키로 에디션을 정한다."""
    if os.environ.get("RO_EDITION_SOURCE") == "license":
        os.environ["RO_EDITION"] = edition()

