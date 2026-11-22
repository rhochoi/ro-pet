"""파일 카드 색인(cards.db). `ro pro` 전용. 원본은 읽기만 하고 본문은 저장하지 않는다.

    ro cards scan [--roots ...]     한 번 훑어 카드를 갱신(주기 작업이 부르는 것과 같다)
    ro cards report                 폴더 건강검진(개수 위주, 읽기 전용)
    ro cards agent                  launchd 주기 작업 설정 파일을 보여 준다(등록은 사용자가 승인한 뒤)
에디션은 RO_EDITION으로만 정한다(번들 앱은 라이선스 키가 정한다). 예전 `--pro` 인자는 받기만 하고 무시한다.

카드 하나 = 사용자가 "같은 파일"이라고 여길 대상 하나. 경로·inode가 바뀌어도 이어지도록
docs/POKE-M0-REPORT.md §3.5 확정 규칙을 따른다.
  1. (dev, ino) 일치 → 같은 카드
  2. 같은 경로에서 inode만 바뀜 → SHA-256 같거나 MinHash(128) Jaccard ≥ 0.5일 때만 같은 카드.
     아니면 새 카드 + "replaced"(표시 전용) 관계. 한쪽이라도 iCloud에만 있으면 새 카드 + "pending" 관계
  3. 사라진 카드와 새 파일의 크기·SHA-256이 같음 → 이동(같은 카드)
  4. 나머지 → 새 카드
저장하는 것: 경로·크기·시각·SHA-256·MinHash 서명(단어 3-gram 해시의 128개 최솟값. 본문을 되살릴 수 없다).
본문·제목은 저장하지 않는다. iCloud에만 있는 파일은 이름·메타만 담고 내려받지 않는다.

쓰는 쪽은 하나다(이 모듈의 scan, 잠금 파일로 줄 세움). 다른 모듈은 read_only=True로 연다.
"""
import argparse
import hashlib
import os
import plistlib
import random
import resource
import sqlite3
import subprocess
import sys
import time
from collections import Counter, defaultdict
from pathlib import Path

from . import config, detect, fsguard, fsutil
from .mapper import SKIP_DIRS, is_sensitive

DB_NAME = "cards.db"
DEFAULT_ROOTS = ["~/Downloads", "~/Desktop", "~/Documents", "~/Library/Mobile Documents/com~apple~CloudDocs"]
WALL_LIMIT = 60.0                  # 한 번 훑는 시간 상한(초)
RSS_LIMIT = 200 * 1024 * 1024      # 바이트
SHA_MAX = 512 * 1024 * 1024        # 이보다 큰 파일은 해시하지 않는다
INTERVAL = 15 * 60                 # launchd 주기
BATTERY_INTERVAL = 60 * 60         # 배터리일 때는 1시간에 한 번만
NUM_PERM = 128
SIMILAR = detect.SIMILAR           # 0.5
GRAMS_CAP = 5000                   # 서명에 쓰는 3-gram 상한(긴 문서의 비용 제한)
LABEL = "dev.ro.cards"
STALE_DAYS = 90

_PRIME = (1 << 61) - 1
_rng = random.Random(0x5EED)
_PERM = [(_rng.randrange(1, _PRIME), _rng.randrange(0, _PRIME)) for _ in range(NUM_PERM)]

SCHEMA = """
CREATE TABLE IF NOT EXISTS cards(
  card_id INTEGER PRIMARY KEY, dev INTEGER, ino INTEGER, path TEXT, ext TEXT, size INTEGER, mtime REAL,
  dataless INTEGER, package INTEGER, sha TEXT, minhash BLOB, first_seen REAL, last_seen REAL, gone REAL);
CREATE INDEX IF NOT EXISTS cards_inode ON cards(dev, ino) WHERE gone IS NULL;
CREATE INDEX IF NOT EXISTS cards_path ON cards(path) WHERE gone IS NULL;
CREATE INDEX IF NOT EXISTS cards_sha ON cards(sha);
CREATE TABLE IF NOT EXISTS relations(a INTEGER, b INTEGER, kind TEXT, at REAL, PRIMARY KEY(a, b, kind));
CREATE TABLE IF NOT EXISTS path_history(card_id INTEGER, path TEXT, at REAL, PRIMARY KEY(card_id, path));
CREATE TABLE IF NOT EXISTS meta(key TEXT PRIMARY KEY, value TEXT);
"""


# ---------- DB ----------
def db_path(home=config.HOME):
    return Path(home).expanduser() / DB_NAME


def connect(home=config.HOME, read_only=False):
    path = db_path(home)
    if read_only:
        if not path.exists():
            return None
        con = sqlite3.connect(f"file:{path}?mode=ro", uri=True, timeout=5)
    else:
        fsutil.ensure_dir(path.parent)
        fd = os.open(path, os.O_RDWR | os.O_CREAT, 0o600)
        os.close(fd)
        con = sqlite3.connect(path, timeout=5)
        con.execute("PRAGMA journal_mode=WAL")
        con.executescript(SCHEMA)
    con.execute("PRAGMA busy_timeout=5000")
    con.row_factory = sqlite3.Row
    return con


def _meta(con, key, value=None):
    if value is None:
        row = con.execute("SELECT value FROM meta WHERE key=?", (key,)).fetchone()
        return row[0] if row else None
    con.execute("INSERT OR REPLACE INTO meta VALUES(?, ?)", (key, str(value)))


# ---------- 서명 ----------
def minhash(grams):
    """단어 3-gram 집합 → 128개 64비트 최솟값(바이트). 서명에서 본문을 되살릴 수 없다."""
    hs = sorted(int.from_bytes(hashlib.blake2b(" ".join(g).encode(), digest_size=8).digest(), "little")
                for g in grams)[:GRAMS_CAP]  # 해시값 순으로 고르면 문서 위치와 무관한 표본이 된다
    sig = [min((a * h + b) % _PRIME for h in hs) for a, b in _PERM]
    return b"".join(v.to_bytes(8, "little") for v in sig)


def similarity(sig_a, sig_b):
    if not sig_a or not sig_b:
        return None
    va = [sig_a[i:i + 8] for i in range(0, len(sig_a), 8)]
    vb = [sig_b[i:i + 8] for i in range(0, len(sig_b), 8)]
    return sum(x == y for x, y in zip(va, vb)) / NUM_PERM


def _fingerprint(p, st, dataless):
    """(sha, minhash). iCloud에만 있거나 너무 크면 해시하지 않는다. 본문 서명은 문서형만."""
    if dataless or st.st_size > SHA_MAX:
        return None, None
    try:
        sha = detect.sha256(p)
    except OSError:
        return None, None
    grams = detect._shingles(p) if p.suffix.lower() in detect_exts() else None
    return sha, (minhash(grams) if grams else None)


def detect_exts():
    from .extract import SUPPORTED
    return SUPPORTED


# ---------- 순회 ----------
def _entries(roots):
    for root in roots:
        root = Path(root).expanduser()
        if not root.is_dir() or root.is_symlink():
            continue
        for p, st, kind in fsguard.walk(root, skip_dirs=SKIP_DIRS):
            # Keynote(.key)처럼 비밀 확장자와 겹치는 패키지는 이름 앞부분으로만 판정한다
            if is_sensitive(p.stem if kind == "package" else p.name) or fsguard.is_lock_file(p.name):
                continue
            yield root, p, st, kind


def _over_budget(started, wall_limit, rss_limit):
    if time.monotonic() - started > wall_limit:
        return "시간"
    rss = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss  # macOS는 바이트
    if sys.platform != "darwin":
        rss *= 1024
    return "메모리" if rss > rss_limit else None


def _upsert(con, p, st, kind, now, card_id=None, sha=None, sig=None):
    dataless = fsguard.is_dataless(p, st)
    row = (st.st_dev, st.st_ino, str(p), p.suffix.lower(), st.st_size, st.st_mtime, int(dataless),
           int(kind == "package"), sha, sig, now)
    if card_id is None:
        cur = con.execute("INSERT INTO cards(dev, ino, path, ext, size, mtime, dataless, package, sha, minhash,"
                          " last_seen, first_seen) VALUES(?,?,?,?,?,?,?,?,?,?,?,?)", row + (now,))
        return cur.lastrowid
    con.execute("UPDATE cards SET dev=?, ino=?, path=?, ext=?, size=?, mtime=?, dataless=?, package=?, sha=?,"
                " minhash=?, last_seen=?, gone=NULL WHERE card_id=?", row + (card_id,))
    return card_id


def _relate(con, a, b, kind, now):
    con.execute("INSERT OR IGNORE INTO relations VALUES(?,?,?,?)", (a, b, kind, now))


def _record_old_path(con, card_id, old_path, now):
    con.execute("INSERT OR IGNORE INTO path_history(card_id, path, at) VALUES(?,?,?)", (card_id, str(old_path), now))
    _relate(con, card_id, card_id, "moved", now)


def scan(roots=None, home=config.HOME, now=None, wall_limit=WALL_LIMIT, rss_limit=RSS_LIMIT, only=None):
    """한 번 훑어 카드를 갱신한다. only=경로 목록이면 그 파일만 본다(Spotlight 보정). 반환: 요약 dict."""
    home_dir = Path.home().resolve()
    # 홈 밖(/, /usr 등)은 카드로 만들지 않는다. Spotlight 보정(only)도 같은 루트만 본다(RO-AUD-106)
    roots = [str(Path(r).expanduser()) for r in (roots or DEFAULT_ROOTS)
             if Path(r).expanduser().resolve().is_relative_to(home_dir)]
    now = now or time.time()
    started = time.monotonic()
    out = Counter()
    stopped = None
    with fsutil.locked(Path(home).expanduser() / "cards.lock"):
        con = connect(home)
        try:
            seen, fresh = set(), []
            if only is not None:
                entries = []
                for raw in only:
                    p = Path(raw)
                    root = next((r for r in roots if str(p).startswith(r + os.sep)), None)
                    st = fsguard._st(p)
                    if root and st and not is_sensitive(p.name):
                        entries.append((root, p, st, "package" if fsguard.is_package(p, st) else "file"))
            else:
                entries = _entries(roots)
            for root, p, st, kind in entries:
                stopped = _over_budget(started, wall_limit, rss_limit)
                if stopped:
                    break
                out["files"] += 1
                dataless = fsguard.is_dataless(p, st)
                row = con.execute("SELECT * FROM cards WHERE dev=? AND ino=? AND gone IS NULL",
                                  (st.st_dev, st.st_ino)).fetchone()
                if row:  # 규칙 1
                    changed = (row["size"], row["mtime"]) != (st.st_size, st.st_mtime) or \
                        (row["dataless"] and not dataless)
                    if dataless or not (changed or row["sha"] is None):
                        sha, sig = row["sha"], row["minhash"]   # 내려받지 않는다 / 바뀐 것이 없다
                    else:
                        sha, sig = _fingerprint(p, st, dataless)
                    if row["path"] != str(p):
                        _record_old_path(con, row["card_id"], row["path"], now)
                        out["moved"] += 1
                    _upsert(con, p, st, kind, now, row["card_id"], sha, sig)
                    seen.add(row["card_id"])
                    out["same"] += 1
                    continue
                sha, sig = _fingerprint(p, st, dataless)
                old = con.execute("SELECT * FROM cards WHERE path=? AND gone IS NULL", (str(p),)).fetchone()
                if old:  # 규칙 2: 같은 경로, 새 inode
                    if not dataless and not old["dataless"] and sha and (
                            sha == old["sha"] or (similarity(sig, old["minhash"]) or 0) >= SIMILAR):
                        _upsert(con, p, st, kind, now, old["card_id"], sha, sig)
                        seen.add(old["card_id"])
                        out["resaved"] += 1
                        continue
                    con.execute("UPDATE cards SET gone=? WHERE card_id=?", (now, old["card_id"]))
                    cid = _upsert(con, p, st, kind, now, None, sha, sig)
                    _relate(con, old["card_id"], cid, "pending" if dataless or old["dataless"] else "replaced", now)
                    seen.add(cid)
                    out["replaced"] += 1
                    continue
                fresh.append((p, st, kind, sha, sig))
            # 규칙 3: 이번에 못 본 카드 중 크기·SHA가 같은 새 파일 → 이동. 다 훑었을 때만 '사라짐'을 판정한다
            full = only is None and not stopped
            missing = {}
            if full:
                for r in con.execute("SELECT * FROM cards WHERE gone IS NULL"):
                    if r["card_id"] not in seen and any(r["path"].startswith(x + os.sep) for x in roots):
                        missing[r["card_id"]] = r
            by_sha = defaultdict(list)
            for r in missing.values():
                if r["sha"]:
                    by_sha[(r["size"], r["sha"])].append(r["card_id"])
            for p, st, kind, sha, sig in fresh:
                ids = by_sha.get((st.st_size, sha)) if sha else None
                if ids:
                    cid = ids.pop(0)
                    prev_row = missing.pop(cid, None)
                    if prev_row and prev_row["path"] != str(p):
                        _record_old_path(con, cid, prev_row["path"], now)
                    _upsert(con, p, st, kind, now, cid, sha, sig)
                    out["moved"] += 1
                else:
                    _upsert(con, p, st, kind, now, None, sha, sig)
                    out["new"] += 1
            for cid in missing:
                con.execute("UPDATE cards SET gone=? WHERE card_id=?", (now, cid))
                out["gone"] += 1
            if only is None:
                _meta(con, "last_scan", now)
                _meta(con, "last_scan_complete", int(full))
            con.commit()
        finally:
            con.close()
    out = dict(out)
    out["stopped"] = stopped
    out["seconds"] = round(time.monotonic() - started, 2)
    return out


def known_sha(path, home=config.HOME):
    """카드에 저장된 SHA-256. 지금 파일의 크기·수정 시각·inode가 카드와 같을 때만 믿는다. 없으면 None."""
    try:
        st = os.stat(path)
        con = connect(home, read_only=True)
    except (OSError, sqlite3.Error):
        return None
    if con is None:
        return None
    try:
        row = con.execute("SELECT sha FROM cards WHERE dev=? AND ino=? AND size=? AND mtime=? AND gone IS NULL",
                          (st.st_dev, st.st_ino, st.st_size, st.st_mtime)).fetchone()
    except sqlite3.Error:
        return None
    finally:
        con.close()
    return row[0] if row else None


def _in_allowed(p, allowed):
    if not allowed:
        return True
    try:
        rp = Path(p).resolve()
    except OSError:
        return False
    return any(rp.is_relative_to(Path(a).resolve()) for a in allowed)


def moved_matches(terms, home=config.HOME, allowed=None, limit=5):
    """이전 이름·경로로 검색했을 때 카드 이동(path_history)·교체(relations) 이력에서 현재 파일을 찾아 돌려준다.
    반환: [(현재 Path, 이전 파일명, kind)]. 읽기 전용."""
    import unicodedata
    clean_terms = [unicodedata.normalize("NFC", str(t)).casefold() for t in (terms or ()) if str(t).strip()]
    if not clean_terms:
        return []
    try:
        con = connect(home, read_only=True)
    except sqlite3.Error:
        return []
    if con is None:
        return []
    hits, seen = [], set()
    try:
        # 1) path_history + relations(moved)에서 이전 경로 대조
        try:
            rows = con.execute(
                "SELECT c.path AS cur_path, h.path AS old_path, 'moved' AS kind "
                "FROM path_history h JOIN cards c ON c.card_id = h.card_id "
                "LEFT JOIN relations r ON r.a = c.card_id AND r.kind = 'moved' "
                "WHERE c.gone IS NULL ORDER BY h.at DESC"
            ).fetchall()
        except sqlite3.OperationalError:
            rows = []
        # 2) relations(replaced / pending)에서 이전 카드 경로 → 현재 카드 경로 대조
        try:
            rep_rows = con.execute(
                "SELECT cur.path AS cur_path, old.path AS old_path, r.kind AS kind "
                "FROM relations r "
                "JOIN cards old ON old.card_id = r.a "
                "JOIN cards cur ON cur.card_id = r.b "
                "WHERE cur.gone IS NULL AND r.kind IN ('replaced', 'pending') ORDER BY r.at DESC"
            ).fetchall()
        except sqlite3.OperationalError:
            rep_rows = []
        for r in (*rows, *rep_rows):
            old_name = unicodedata.normalize("NFC", Path(r["old_path"]).name).casefold()
            if not all(t in old_name for t in clean_terms):
                continue
            cur_p = Path(r["cur_path"])
            if cur_p in seen or not cur_p.is_file() or cur_p.is_symlink() or not _in_allowed(cur_p, allowed):
                continue
            seen.add(cur_p)
            hits.append((cur_p, Path(r["old_path"]).name, r["kind"]))
            if len(hits) >= limit:
                break
    except sqlite3.Error:
        return []
    finally:
        con.close()
    return hits


def related_cards(path, home=config.HOME, allowed=None, limit=3, threshold=SIMILAR):
    """relations(replaced·pending) 및 minhash(Jaccard >= threshold)로 현재 파일과 관련된 다른 문서를 찾는다.
    반환: [{"path": Path, "reason": str, "similarity": float|None, "mtime": float}]. 읽기 전용."""
    p = Path(path)
    try:
        st = os.stat(p)
        con = connect(home, read_only=True)
    except (OSError, sqlite3.Error):
        return []
    if con is None:
        return []
    out, seen = [], {str(p), str(p.resolve())}
    try:
        me = con.execute(
            "SELECT card_id, path, minhash, ext FROM cards WHERE gone IS NULL AND (path=? OR (dev=? AND ino=?)) LIMIT 1",
            (str(p), st.st_dev, st.st_ino),
        ).fetchone()
        if me is None:
            return []
        cid, my_sig = me["card_id"], me["minhash"]
        # 1) 명시적 관계(relations)
        rel_rows = con.execute(
            "SELECT c.path, c.mtime, r.kind FROM relations r "
            "JOIN cards c ON (c.card_id = CASE WHEN r.a = ? THEN r.b ELSE r.a END) "
            "WHERE (r.a = ? OR r.b = ?) AND c.card_id != ? AND c.gone IS NULL",
            (cid, cid, cid, cid),
        ).fetchall()
        for r in rel_rows:
            cp = Path(r["path"])
            if str(cp) in seen or not cp.is_file() or cp.is_symlink() or not _in_allowed(cp, allowed):
                continue
            seen.add(str(cp))
            out.append({"path": cp, "reason": "이전 판본 관계(카드)" if r["kind"] == "replaced" else "관련 카드",
                        "similarity": None, "mtime": r["mtime"]})
        # 2) MinHash 내용 유사 문서
        if my_sig:
            cand_rows = con.execute(
                "SELECT card_id, path, mtime, minhash FROM cards WHERE gone IS NULL AND card_id != ? AND minhash IS NOT NULL",
                (cid,),
            ).fetchall()
            scored = []
            for r in cand_rows:
                sim = similarity(my_sig, r["minhash"])
                if sim is not None and sim >= threshold:
                    cp = Path(r["path"])
                    if str(cp) in seen or str(cp.resolve()) in seen or not cp.is_file() or cp.is_symlink():
                        continue
                    if not _in_allowed(cp, allowed):
                        continue
                    scored.append((sim, cp, r["mtime"]))
            for sim, cp, mt in sorted(scored, key=lambda x: (-x[0], -x[2]))[:max(0, limit - len(out))]:
                seen.add(str(cp))
                out.append({"path": cp, "reason": f"내용 유사 {int(round(sim * 100))}%(카드)",
                            "similarity": round(sim, 3), "mtime": mt})
    except sqlite3.Error:
        return []
    finally:
        con.close()
    return out[:limit]


# ---------- 주기 실행 ----------
def on_battery(runner=subprocess.run):
    try:
        r = runner(["pmset", "-g", "batt"], capture_output=True, text=True, timeout=5)
    except (OSError, subprocess.TimeoutExpired):
        return False
    return "Battery Power" in r.stdout


def periodic(home=config.HOME, roots=None, now=None, runner=subprocess.run):
    """launchd가 15분마다 부른다. 배터리일 때는 지난 실행에서 1시간이 지나야 돈다."""
    now = now or time.time()
    con = connect(home)
    try:
        last = float(_meta(con, "last_scan") or 0)
    finally:
        con.close()
    if on_battery(runner) and now - last < BATTERY_INTERVAL:
        return {"skipped": "배터리"}
    res = scan(roots, home, now)
    if not res.get("stopped"):  # 하루 사이 바뀐 파일 중 놓친 것이 없게 Spotlight로 한 번 더 본다
        changed = spotlight_changes(roots, runner=runner)
        if changed:
            res["spotlight"] = scan(roots, home, now, only=changed).get("files", 0)
    return res


def spotlight_changes(roots=None, hours=24, runner=subprocess.run):
    """최근 바뀐 파일 경로(Spotlight). 실패하면 빈 목록."""
    out = []
    for root in roots or DEFAULT_ROOTS:
        r = Path(root).expanduser()
        if not r.is_dir():
            continue
        try:
            res = runner(["mdfind", "-onlyin", str(r), f"kMDItemFSContentChangeDate >= $time.now(-{hours * 3600})"],
                         capture_output=True, text=True, timeout=20)
        except (OSError, subprocess.TimeoutExpired):
            continue
        out += [x for x in res.stdout.splitlines() if x]
    return out


def agent_plist(python=sys.executable, home=config.HOME):
    """launchd 사용자 에이전트 설정. 이 함수는 파일을 쓰지 않는다(등록은 사용자 승인 뒤 별도)."""
    return {
        "Label": LABEL,
        "ProgramArguments": [python, "-m", "ro", "cards", "periodic"],
        "StartInterval": INTERVAL,
        "RunAtLoad": False,
        "LowPriorityIO": True,
        "ProcessType": "Background",
        "Nice": 10,
        "EnvironmentVariables": {"RO_EDITION": "pro", "RO_HOME": str(Path(home).expanduser())},
    }


# ---------- 폴더 건강검진(읽기 전용) ----------
def report(home=config.HOME, now=None):
    """카드에서 개수만 뽑는다. 반환: {루트 이름: {...}} + 전체 중복·옛 판."""
    now = now or time.time()
    con = connect(home, read_only=True)
    if con is None:
        return None
    try:
        rows = con.execute("SELECT * FROM cards WHERE gone IS NULL").fetchall()
        last = _meta(con, "last_scan")
    finally:
        con.close()
    per = defaultdict(Counter)
    for r in rows:
        top = _root_label(r["path"])
        c = per[top]
        c["파일"] += 1
        c["iCloud에만 있음"] += r["dataless"]
        c["패키지"] += r["package"]
        if not r["dataless"] and now - r["mtime"] > STALE_DAYS * 86400:
            c[f"{STALE_DAYS}일 넘게 안 바뀜"] += 1
            c["오래된 용량(MB)"] += r["size"] // (1024 * 1024)
    groups = defaultdict(list)
    for r in rows:
        if r["sha"]:
            groups[(r["size"], r["sha"])].append(r)
    dups = [g for g in groups.values() if len(g) > 1]
    versions = detect.version_groups([(Path(r["path"]), _StatLike(r)) for r in rows if not r["package"]])
    return {"마지막 훑기": time.strftime("%Y-%m-%d %H:%M", time.localtime(float(last))) if last else None,
            "폴더": {k: dict(v) for k, v in sorted(per.items())},
            "같은 내용 묶음": len(dups), "같은 내용 남는 사본": sum(len(g) - 1 for g in dups),
            "판 여러 개인 문서 묶음": len(versions)}


class _StatLike:
    def __init__(self, r):
        self.st_size, self.st_mtime = r["size"], r["mtime"]


def _root_label(path):
    for raw in DEFAULT_ROOTS:
        r = str(Path(raw).expanduser())
        if path == r or path.startswith(r + os.sep):
            return "iCloud Drive" if "CloudDocs" in raw else Path(raw).name
    return "기타"


def _print_report(rep):
    if rep is None:
        print("아직 카드가 없습니다. `ro cards scan`을 먼저 실행하세요.")
        return
    print(f"폴더 건강검진 (마지막 훑기: {rep['마지막 훑기'] or '없음'})")
    for name, c in rep["폴더"].items():
        print(f"## {name}")
        for k, v in c.items():
            print(f"  {k}: {v}")
    print(f"같은 내용 묶음 {rep['같은 내용 묶음']}개(남는 사본 {rep['같은 내용 남는 사본']}개), "
          f"판이 여러 개인 문서 묶음 {rep['판 여러 개인 문서 묶음']}개")
    print("읽기 전용 보고입니다. 아무것도 옮기거나 지우지 않았습니다.")


# ---------- CLI ----------
def _under_home(raw, label, must_exist=False):
    """CLI 경로는 홈 폴더 아래 실제 폴더만 받는다(RO-AUD-106: 없는 폴더를 조용히 넘기고 홈 밖도 색인·저장했다)."""
    if not str(raw).strip():
        raise ValueError(f"{label} 경로가 비어 있습니다.")
    p = Path(raw).expanduser()
    if must_exist and not p.is_dir():
        raise ValueError(f"폴더가 없습니다: {raw}")
    home = Path.home().resolve()
    real = p.resolve()
    if real == home or not real.is_relative_to(home):
        raise ValueError(f"{label}는 홈 폴더 아래 폴더만 쓸 수 있습니다: {raw}")
    return real


def _is_pro():
    # 에디션은 환경(번들 앱에서는 라이선스 키가 정한 값)만 따른다. 인자로 켤 수 없다(RO-AUD-104)
    return os.environ.get("RO_EDITION") == "pro"


def main(argv=None):
    ap = argparse.ArgumentParser(prog="ro cards", description="파일 카드 색인(ro pro 전용, 읽기 전용)")
    ap.add_argument("--pro", action="store_true", help=argparse.SUPPRESS)  # 예전 launchd 설정 호환용. 에디션을 바꾸지 않는다
    ap.add_argument("--home", default=os.environ.get("RO_HOME", config.HOME))
    sub = ap.add_subparsers(dest="cmd", required=True)
    sc = sub.add_parser("scan", help="한 번 훑어 카드 갱신")
    sc.add_argument("--roots", nargs="+")
    sub.add_parser("periodic", help="주기 작업용(배터리 간격·Spotlight 보정 포함)")
    sub.add_parser("report", help="폴더 건강검진")
    sub.add_parser("agent", help="launchd 설정 미리 보기(등록하지 않음)")
    a = ap.parse_args(argv)
    if not _is_pro():
        print("ro pro 전용 기능입니다.", file=sys.stderr)
        return 2
    try:
        a.home = str(_under_home(a.home, "--home"))
        if a.cmd == "scan" and a.roots:
            a.roots = [str(_under_home(r, "--roots", must_exist=True)) for r in a.roots]
    except ValueError as e:
        print(str(e), file=sys.stderr)
        return 1
    try:
        if a.cmd == "scan":
            print(scan(a.roots, a.home))
        elif a.cmd == "periodic":
            print(periodic(a.home))
        elif a.cmd == "report":
            _print_report(report(a.home))
    except sqlite3.OperationalError as e:
        if "locked" not in str(e) and "busy" not in str(e):
            raise
        # 다른 프로세스가 cards.db를 잡고 있다. 이번 훑기는 통째로 되돌려졌으니(커밋 전) 다음에 다시 하면 된다(RO-AUD-102)
        print("카드 색인이 다른 작업에 잠겨 있어 이번에는 건너뜁니다. 잠시 뒤 다시 실행하세요.", file=sys.stderr)
        return 1
    if a.cmd == "agent":
        print(plistlib.dumps(agent_plist(home=a.home)).decode())
        print(f"# 등록하려면(사용자가 직접): ~/Library/LaunchAgents/{LABEL}.plist로 저장 후 "
              f"launchctl bootstrap gui/$(id -u) ~/Library/LaunchAgents/{LABEL}.plist")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
