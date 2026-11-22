"""작업 패턴 프로파일(memory.db). `ro pro` 전용, 사용자가 한 번 명시적으로 동의한 뒤에만 쌓는다(원칙 6, A3).

저장하는 것은 메타 통계뿐이다. 파일명·경로·본문은 담지 않는다.
  - 폴더는 이 기기에만 있는 비밀 소금으로 만든 HMAC 토큰으로만 남긴다. 화면에 보일 때만 지금 있는 폴더를
    다시 해시해 맞춰 본다(맞는 폴더가 없으면 '사라진 폴더'로 보인다).
  - 키는 확장자(.pdf)·시간대(오전/오후/저녁)·검색 종류처럼 이름이 아닌 값만 받는다.

배우는 방식
  - 관측 → 에피소드: 같은 패턴은 15분 안에 다시 보이면 한 에피소드로 잇고, 30분을 넘으면 새 에피소드.
  - 하루 상한: 한 패턴은 하루에 한 번만 센다.
  - 승격: 서로 다른 3일에 보이고 가중치가 1.5 이상이면 '배운 것'이 된다. 그 전에는 '보는 중'.
  - 감쇠: 날마다 반감기 24일(21~28일 범위)로 줄어든다. 0.25 아래로 떨어지면 지운다(고정한 것은 빼고).
사용자는 `ro가 배운 것`(펫 패널·`ro learned`)에서 언제든 보고·고정하고·끄고·지울 수 있다. 끈 항목은
다시 배우지 않는다. 동의를 끄면 더는 쌓지 않고, `wipe`는 DB와 소금을 함께 지운다.
"""
import hashlib
import hmac
import os
import secrets
import sqlite3
import time
from pathlib import Path

from . import config, fsutil

DB_NAME = "memory.db"
CONSENT = "profile_learning"
EPISODE_GAP = 15 * 60
EPISODE_MAX = 30 * 60
PROMOTE_DAYS = 3
PROMOTE_WEIGHT = 1.5
HALF_LIFE_DAYS = 24
FORGET_BELOW = 0.25
MAX_KEY = 40
BUSY_MS = 5000             # 다른 쓰기가 끝나길 기다리는 시간. 넘으면 이번 관측은 버린다(observe_quiet)
# 배울 수 있는 패턴 종류. 키와 값이 무엇인지 고정해 둔다(이름·경로가 끼어들 틈을 줄인다)
KINDS = {
    "ext_home": ("확장자", "폴더"),        # .pdf 파일을 주로 두는 폴더
    "pick_folder": ("찾는 종류", "폴더"),  # 이런 종류를 찾을 때 고른 폴더
    "app_band": ("시간대", "앱"),          # 이 시간대에 자주 앞에 두는 앱
}
FOLDER_KINDS = {"ext_home", "pick_folder"}
BANDS = ("새벽", "오전", "오후", "저녁")

SCHEMA = """
CREATE TABLE IF NOT EXISTS patterns(
  id INTEGER PRIMARY KEY, kind TEXT, key TEXT, value TEXT, days TEXT DEFAULT '', first REAL, last REAL,
  ep_start REAL, ep_last REAL, episodes INTEGER DEFAULT 0, pinned INTEGER DEFAULT 0, off INTEGER DEFAULT 0,
  UNIQUE(kind, key, value));
CREATE TABLE IF NOT EXISTS meta(key TEXT PRIMARY KEY, value TEXT);
"""


class NotAllowed(Exception):
    """동의 전이거나 mini라서 배우지 않는다."""


def db_path(home=config.HOME):
    return Path(home).expanduser() / DB_NAME


def consented(home=config.HOME):
    return config.load(home).get(CONSENT) is True


def set_consent(home=config.HOME, on=True):
    config.update(home, **{CONSENT: bool(on)})
    return bool(on)


def _connect(home, create=False):
    path = db_path(home)
    if not path.exists():
        if not create:
            return None
        fsutil.ensure_dir(path.parent)
        os.close(os.open(path, os.O_RDWR | os.O_CREAT, 0o600))
    con = sqlite3.connect(path, timeout=BUSY_MS / 1000)
    con.execute(f"PRAGMA busy_timeout={int(BUSY_MS)}")
    con.execute("PRAGMA journal_mode=WAL")
    con.executescript(SCHEMA)
    con.row_factory = sqlite3.Row
    return con


def _salt(con):
    row = con.execute("SELECT value FROM meta WHERE key='salt'").fetchone()
    if row:
        return bytes.fromhex(row[0])
    salt = secrets.token_bytes(16)
    con.execute("INSERT INTO meta VALUES('salt', ?)", (salt.hex(),))
    return salt


def _token(salt, folder):
    norm = os.path.realpath(str(Path(folder).expanduser()))
    return "T" + hmac.new(salt, norm.encode("utf-8"), hashlib.sha256).hexdigest()[:16]


def band(ts):
    h = time.localtime(ts).tm_hour
    return BANDS[0] if h < 6 else BANDS[1] if h < 12 else BANDS[2] if h < 18 else BANDS[3]


def _day(ts):
    return time.strftime("%Y-%m-%d", time.localtime(ts))


def _weight(days, now):
    total = 0.0
    for d in days:
        age = (now - time.mktime(time.strptime(d, "%Y-%m-%d"))) / 86400
        total += 0.5 ** (max(age, 0) / HALF_LIFE_DAYS)
    return total


def _days(row):
    return [d for d in (row["days"] or "").split(",") if d]


def _check_key(kind, key):
    if kind not in KINDS:
        raise ValueError(f"모르는 패턴 종류: {kind}")
    key = str(key)
    if not key or len(key) > MAX_KEY or "/" in key or "\\" in key or "\n" in key:
        raise ValueError("패턴 키에는 이름·경로를 넣지 않습니다")
    return key


def observe(kind, key, value, home=config.HOME, now=None):
    """한 번 관측. value는 폴더 종류면 실제 폴더 경로(여기서 토큰으로 바꾸고 버린다), 앱 종류면 앱 이름.
    동의 전이면 NotAllowed. 반환: 이번 관측으로 하루 수가 늘었는지."""
    if not consented(home):
        raise NotAllowed("동의 전에는 배우지 않습니다")
    key = _check_key(kind, key)
    now = time.time() if now is None else now
    con = _connect(home, create=True)
    try:
        with con:
            val = _token(_salt(con), value) if kind in FOLDER_KINDS else str(value)[:MAX_KEY]
            if kind not in FOLDER_KINDS and ("/" in val or "\n" in val):
                raise ValueError("값에는 경로를 넣지 않습니다")
            row = con.execute("SELECT * FROM patterns WHERE kind=? AND key=? AND value=?", (kind, key, val)).fetchone()
            if row is None:
                con.execute("INSERT INTO patterns(kind, key, value, days, first, last, ep_start, ep_last, episodes) "
                            "VALUES(?, ?, ?, ?, ?, ?, ?, ?, 1)", (kind, key, val, _day(now), now, now, now, now))
                return True
            if row["off"]:
                return False                        # 끈 항목은 다시 배우지 않는다
            same_episode = now - row["ep_last"] < EPISODE_GAP and now - row["ep_start"] < EPISODE_MAX
            ep_start = row["ep_start"] if same_episode else now
            episodes = row["episodes"] + (0 if same_episode else 1)
            days = _days(row)
            grew = _day(now) not in days and not same_episode
            if grew:
                days.append(_day(now))
            con.execute("UPDATE patterns SET days=?, last=?, ep_start=?, ep_last=?, episodes=? WHERE id=?",
                        (",".join(days[-60:]), now, ep_start, now, episodes, row["id"]))
            return grew
    finally:
        con.close()


def observe_quiet(kind, key, value, home=config.HOME, now=None):
    """다른 기능(찾기 선택·정리 승인·앞 앱)이 곁들여 부르는 입구. ro pro이고 동의했을 때만 배우고,
    무슨 일이 있어도 부른 쪽을 멈추지 않는다. mini(RO_EDITION≠pro)에서는 DB를 만들지도 않는다."""
    if os.environ.get("RO_EDITION") != "pro" or not consented(home):
        return False
    try:
        return observe(kind, key, value, home=home, now=now)
    except (NotAllowed, ValueError, OSError, sqlite3.Error):
        return False


def decay(home=config.HOME, now=None):
    """감쇠로 약해진 항목을 지운다(고정·끈 항목은 남긴다). 반환: 지운 수."""
    now = time.time() if now is None else now
    con = _connect(home)
    if con is None:
        return 0
    try:
        with con:
            gone = [r["id"] for r in con.execute("SELECT * FROM patterns WHERE pinned=0 AND off=0")
                    if _weight(_days(r), now) < FORGET_BELOW]
            con.executemany("DELETE FROM patterns WHERE id=?", [(i,) for i in gone])
        return len(gone)
    finally:
        con.close()


def _status(row, weight):
    if row["off"]:
        return "off"
    if row["pinned"]:
        return "pinned"
    if len(_days(row)) >= PROMOTE_DAYS and weight >= PROMOTE_WEIGHT:
        return "learned"
    return "watching"


def _folder_names(salt, roots):
    """지금 있는 폴더를 다시 해시해 토큰 → 보이는 이름. 화면에 보일 때만 하고 저장하지 않는다."""
    names, home = {}, Path.home()
    for root in roots:
        base = Path(root).expanduser()
        if not base.is_dir():
            continue
        for dirpath, dirs, _files in os.walk(base):
            depth = len(Path(dirpath).relative_to(base).parts)
            dirs[:] = [d for d in dirs if not d.startswith(".")] if depth < 3 else []
            p = Path(dirpath)
            try:
                label = "~/" + str(p.relative_to(home))
            except ValueError:
                label = str(p)
            names.setdefault(_token(salt, p), label)
    return names


def learned(home=config.HOME, now=None, roots=None):
    """`ro가 배운 것` 한 화면. 반환: [{id, kind, what, key, value, days, weight, status}] — 상태 순."""
    now = time.time() if now is None else now
    decay(home, now)
    con = _connect(home)
    if con is None:
        return []
    try:
        rows = con.execute("SELECT * FROM patterns").fetchall()
        salt_row = con.execute("SELECT value FROM meta WHERE key='salt'").fetchone()
    finally:
        con.close()
    names = {}
    if salt_row and any(r["kind"] in FOLDER_KINDS for r in rows):
        from . import cards
        names = _folder_names(bytes.fromhex(salt_row[0]), roots or cards.DEFAULT_ROOTS)
    out = []
    for r in rows:
        w = _weight(_days(r), now)
        value = names.get(r["value"], "사라진 폴더") if r["kind"] in FOLDER_KINDS else r["value"]
        what = KINDS[r["kind"]]
        out.append({"id": r["id"], "kind": r["kind"], "what": f"{what[0]} {r['key']} → {what[1]} {value}",
                    "key": r["key"], "value": value, "days": len(_days(r)), "weight": round(w, 2),
                    "status": _status(r, w)})
    order = {"pinned": 0, "learned": 1, "watching": 2, "off": 3}
    return sorted(out, key=lambda x: (order[x["status"]], -x["weight"]))


def prior(kind, key, home=config.HOME, now=None):
    """배운(승격·고정) 값만 가중치 순으로. 폴더는 토큰이므로 folder_matches로 대조한다. 동의 전이면 빈 목록."""
    if not consented(home):
        return []
    now = time.time() if now is None else now
    con = _connect(home)
    if con is None:
        return []
    try:
        rows = con.execute("SELECT * FROM patterns WHERE kind=? AND key=? AND off=0", (kind, str(key))).fetchall()
    finally:
        con.close()
    scored = [(r["value"], _weight(_days(r), now)) for r in rows]
    keep = [(v, w) for (v, w), r in zip(scored, rows) if _status(r, w) in ("learned", "pinned")]
    return [v for v, _ in sorted(keep, key=lambda x: -x[1])]


def folder_token(folder, home=config.HOME):
    """폴더 경로 → 저장된 토큰과 같은 형식(대조용). DB가 없으면 None."""
    con = _connect(home)
    if con is None:
        return None
    try:
        row = con.execute("SELECT value FROM meta WHERE key='salt'").fetchone()
        return _token(bytes.fromhex(row[0]), folder) if row else None
    finally:
        con.close()


def preferred_folders(kind, key, home=config.HOME, now=None, roots=None):
    """배운(승격·고정) 폴더 토큰을 현재 존재하는 실제 폴더 경로 목록으로 돌려준다(가중치 순).
    DB에는 여전히 토큰만 남고, 여기서만 지금 있는 폴더를 다시 해시해 대조한다."""
    if kind not in FOLDER_KINDS:
        return []
    tokens = prior(kind, key, home=home, now=now)
    if not tokens:
        return []
    con = _connect(home)
    if con is None:
        return []
    try:
        salt_row = con.execute("SELECT value FROM meta WHERE key='salt'").fetchone()
    finally:
        con.close()
    if not salt_row:
        return []
    salt = bytes.fromhex(salt_row[0])
    wanted = set(tokens)
    found = {}
    if roots is None:
        from . import cards
        roots = cards.DEFAULT_ROOTS
    for root in roots:
        base = Path(root).expanduser()
        if not base.is_dir() or base.is_symlink():
            continue
        for dirpath, dirs, _files in os.walk(base):
            depth = len(Path(dirpath).relative_to(base).parts)
            dirs[:] = [d for d in dirs if not d.startswith(".")] if depth < 3 else []
            p = Path(dirpath)
            tok = _token(salt, p)
            if tok in wanted and tok not in found:
                found[tok] = p
                if len(found) == len(wanted):
                    break
        if len(found) == len(wanted):
            break
    return [found[t] for t in tokens if t in found]


def _set(home, pid, **cols):
    con = _connect(home)
    if con is None:
        return False
    try:
        with con:
            if cols.get("delete"):
                cur = con.execute("DELETE FROM patterns WHERE id=?", (int(pid),))
            else:
                sets = ", ".join(f"{k}=?" for k in cols)
                cur = con.execute(f"UPDATE patterns SET {sets} WHERE id=?", (*cols.values(), int(pid)))
            return cur.rowcount == 1
    finally:
        con.close()


def pin(pid, on=True, home=config.HOME):
    return _set(home, pid, pinned=int(bool(on)))


def turn_off(pid, off=True, home=config.HOME):
    return _set(home, pid, off=int(bool(off)), pinned=0)


def forget(pid, home=config.HOME):
    return _set(home, pid, delete=True)


def wipe(home=config.HOME):
    """DB·소금을 지우고 동의도 끈다. 되돌릴 수 없다(호출하는 쪽이 사용자 확인을 받는다)."""
    set_consent(home, False)
    removed = False
    for suffix in ("", "-wal", "-shm"):
        p = Path(str(db_path(home)) + suffix)
        if p.exists():
            p.unlink()
            removed = True
    return removed


def main(argv=None):
    """ro learned [list|on|off|pin ID|unpin ID|mute ID|unmute ID|forget ID|wipe --yes] — ro pro 전용."""
    import argparse
    import sys
    if os.environ.get("RO_EDITION") != "pro":
        print("ro pro 전용 기능입니다(RO_EDITION=pro).", file=sys.stderr)
        return 2
    ap = argparse.ArgumentParser(prog="ro learned", description="ro가 배운 것: 보기·고정·끄기·지우기")
    ap.add_argument("action", nargs="?", default="list",
                    choices=["list", "on", "off", "pin", "unpin", "mute", "unmute", "forget", "wipe"])
    ap.add_argument("id", nargs="?", type=int)
    ap.add_argument("--yes", action="store_true", help="wipe 확인")
    args = ap.parse_args(argv)
    a = args.action
    if a in ("on", "off"):
        set_consent(config.HOME, a == "on")
        print("학습을 켰어요. 파일 이름·경로·내용은 남기지 않아요." if a == "on" else "학습을 껐어요. 배운 것은 남아 있어요.")
        return 0
    if a == "wipe":
        if not args.yes:
            print("배운 것을 모두 지우고 학습을 끕니다. 되돌릴 수 없어요. 계속하려면 --yes", file=sys.stderr)
            return 1
        wipe(config.HOME)
        print("모두 지웠어요.")
        return 0
    if a != "list":
        if args.id is None:
            print("번호가 필요해요(ro learned list로 확인).", file=sys.stderr)
            return 2
        fn = {"pin": lambda i: pin(i, True), "unpin": lambda i: pin(i, False), "mute": turn_off,
              "unmute": lambda i: turn_off(i, False), "forget": forget}[a]
        if not fn(args.id):
            print("그 번호를 찾지 못했어요.", file=sys.stderr)
            return 1
    print(f"학습 {'켜짐' if consented() else '꺼짐'}")
    names = {"learned": "배움", "watching": "보는 중", "pinned": "고정", "off": "꺼 둠"}
    for it in learned():
        print(f"  [{it['id']}] {names[it['status']]:<4} {it['what']} · {it['days']}일")
    return 0
