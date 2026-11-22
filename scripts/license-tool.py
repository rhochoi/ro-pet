#!/usr/bin/env python3
"""ro pro 라이선스 키 도구(발급하는 사람 전용). 앱에는 들어가지 않는다.

  keygen --out 경로           서명용 개인 시드를 만들어 경로에 0600으로 저장하고, 공개 키 hex만 출력
                              → 출력된 공개 키를 ro/license.py의 PUBLIC_KEYS에 kid와 함께 넣는다
  issue --secret 경로 --kid ID --id 라이선스ID (--days N | --until YYYY-MM-DD)
                              키 문자열을 출력(수동 발급·시험용. 운영 발급은 결제 웹훅 함수가 한다)

개인 시드는 저장소 안에 두지 않는다(원칙 2). 저장소 안 경로는 거부한다.
"""
import argparse
import calendar
import os
import secrets
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from ro import _ed25519, license  # noqa: E402


def _outside_repo(path):
    p = Path(path).expanduser().resolve()
    if p == ROOT or ROOT in p.parents:
        raise SystemExit(f"저장소 안에는 개인 키를 둘 수 없습니다: {p}")
    return p


def keygen(out):
    p = _outside_repo(out)
    seed = secrets.token_bytes(32)
    fd = os.open(p, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)  # 이미 있으면 덮어쓰지 않는다
    with os.fdopen(fd, "w") as f:
        f.write(seed.hex() + "\n")
    print(_ed25519.public_key(seed).hex())
    print(f"개인 시드를 {p}에 저장했습니다(0600). 백업하고, 잃으면 새 키를 다시 발급해야 합니다.", file=sys.stderr)


def issue(secret, kid, lic_id, days=None, until=None):
    seed = bytes.fromhex(_outside_repo(secret).read_text().strip())
    now = int(time.time())
    if until:
        try:
            exp = calendar.timegm(time.strptime(until, "%Y-%m-%d")) + 86400  # 그날 끝(UTC)까지
        except ValueError:
            raise SystemExit(f"--until은 YYYY-MM-DD 형식의 실제 날짜여야 합니다: {until}") from None
    else:
        if int(days) < 1:
            raise SystemExit("--days는 1 이상이어야 합니다.")
        exp = now + int(days) * 86400
    if exp <= now:
        raise SystemExit(f"만료일이 이미 지났습니다: {until}")
    payload = {"v": 1, "kid": kid, "id": lic_id, "plan": "pro", "iat": now, "exp": exp}
    key = license.encode(payload, seed)
    try:
        license.parse(key, now=now, keys={kid: _ed25519.public_key(seed).hex()})  # 자기 검사
    except license.LicenseError as e:
        raise SystemExit(f"발급한 키가 자기 검사를 통과하지 못했습니다: {e}") from None
    print(key)


def main(argv=None):
    ap = argparse.ArgumentParser(prog="license-tool.py")
    sub = ap.add_subparsers(dest="cmd", required=True)
    kg = sub.add_parser("keygen")
    kg.add_argument("--out", required=True)
    isu = sub.add_parser("issue")
    isu.add_argument("--secret", required=True)
    isu.add_argument("--kid", required=True)
    isu.add_argument("--id", required=True)
    when = isu.add_mutually_exclusive_group(required=True)
    when.add_argument("--days", type=int)
    when.add_argument("--until")
    a = ap.parse_args(argv)
    if a.cmd == "keygen":
        keygen(a.out)
    else:
        issue(a.secret, a.kid, a.id, a.days, a.until)


if __name__ == "__main__":
    main()
