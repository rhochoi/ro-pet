"""용량 감사(읽기 전용): 다시 만들어지는 캐시·SQLite 빈 공간·오래 안 쓴 앱이 차지하는 디스크 공간을 잰다.

원칙
- 아무것도 지우거나 옮기거나 쓰지 않는다. 결과는 화면(또는 --json)으로만 낸다.
- 크기는 lstat의 st_blocks(실제 디스크 블록)로 잰다. 심볼릭 링크와 다른 볼륨(마운트)은 따라가지 않는다.
  APFS 복제(clone) 파일은 블록을 공유해도 각각 센다 → 회수량은 [추정]이다.
- 읽지 못한 항목은 errors로 센다. 시간 예산을 넘기면 partial로 표시한다(조용히 버리지 않는다).
- 브라우저 프로필·iPhone 백업·com.apple.* 같은 민감 폴더는 들어가지 않는다. 비밀 이름(mapper.is_secret)은 세지 않는다.
- SQLite는 파일 앞 100바이트 헤더만 읽어 빈 페이지 수를 낸다(DB를 열지 않으므로 잠금·-shm 생성 없음).
  WAL 모드 DB는 헤더가 최신이 아닐 수 있다 → [추정].
- 오래 안 쓴 앱은 참고용이다. never_recorded는 Spotlight가 꺼졌거나 기록이 없는 경우도 포함한다.

출처: mac-storage-optimizer v1.1(사용자 제공 스킬)의 감사 엔진을 ro 원칙에 맞게 옮겼다.

ro pro: 오래 손대지 않은 프로젝트의 다시 만들 수 있는 빌드 폴더(.venv·node_modules)를 찾고(dead_builds),
사용자가 승인하면 저널 V2로 격리한다(quarantine_builds). 지우지 않고, 1초 안에 되돌릴 수 있다.
"""
import os
import shutil
import stat
import subprocess
import time
from datetime import datetime, timezone
from pathlib import Path

from . import config, fsutil, journal, mapper
from .mapper import is_sensitive

STALE_DAYS = 90
MIN_BYTES = 10 * 1024 * 1024
SQLITE_MIN_FREE = 10 * 1024 * 1024
SQLITE_EXT = (".db", ".sqlite", ".sqlite3")
SQLITE_MAGIC = b"SQLite format 3\x00"
# Application Support 아래에서 들어가지 않는 폴더(브라우저 프로필·기기 백업·OS 데이터)
SKIP_APP_SUPPORT = {"Google", "BraveSoftware", "Firefox", "Microsoft Edge", "Arc", "Naver", "Vivaldi",
                    "com.operasoftware.Opera", "Chromium", "Safari", "Whale", "MobileSync", "AddressBook",
                    "CallHistoryDB", "CallHistoryTransactions", "Knowledge", "1Password", "Bitwarden"}
# 앱 지원 폴더 안의 웹뷰(Electron 등) 캐시. 앱이 다시 만든다.
APP_CACHE_GLOBS = ("Cache", "Code Cache", "GPUCache", "CachedData", "Service Worker/CacheStorage",
                   "Partitions/*/Cache", "Partitions/*/Code Cache", "Partitions/*/GPUCache",
                   "Partitions/*/Service Worker/CacheStorage", "*/*/Code Cache")
DEV_CACHES = ((".npm/_cacache", "npm 캐시"), (".npm/_npx", "npx 실행 캐시"),
              ("Library/Developer/Xcode/DerivedData", "Xcode 빌드 산출물"),
              ("Library/Developer/CoreSimulator/Caches", "시뮬레이터 캐시"),
              (".gradle/caches", "Gradle 캐시"))
UPDATE_LEFTOVER = (".shipit", "-updater")


def _skip_dir(name):
    return name.startswith("com.apple.") or name in SKIP_APP_SUPPORT or is_sensitive(name)


def measure(path, deadline=None):
    """디스크 사용량(바이트), 파일 수, 읽기 오류 수, 완료 여부. 링크·다른 볼륨은 따라가지 않는다."""
    path = Path(path)
    try:
        top = path.lstat()
    except OSError:
        return {"bytes": 0, "files": 0, "errors": 1, "complete": True}
    if not stat.S_ISDIR(top.st_mode):
        return {"bytes": top.st_blocks * 512 if stat.S_ISREG(top.st_mode) else 0,
                "files": int(stat.S_ISREG(top.st_mode)), "errors": 0, "complete": True}
    total = files = errors = 0
    stack = [str(path)]
    while stack:
        if deadline is not None and time.monotonic() > deadline:
            return {"bytes": total, "files": files, "errors": errors, "complete": False}
        d = stack.pop()
        try:
            with os.scandir(d) as it:
                for e in it:
                    if is_sensitive(e.name):
                        continue
                    try:
                        st = e.stat(follow_symlinks=False)
                    except OSError:
                        errors += 1
                        continue
                    if stat.S_ISDIR(st.st_mode):
                        if st.st_dev == top.st_dev:
                            stack.append(e.path)
                    elif stat.S_ISREG(st.st_mode):
                        total += st.st_blocks * 512
                        files += 1
        except OSError:
            errors += 1
    return {"bytes": total, "files": files, "errors": errors, "complete": True}


def _item(path, home, kind, label, deadline):
    m = measure(path, deadline)
    return {"path": str(path), "display": _display(path, home), "kind": kind, "label": label, **m}


def _display(path, home):
    path, home = str(path), str(home)
    return "~" + path[len(home):] if path == home or path.startswith(home + os.sep) else path


def _is_dir(p):
    try:
        return stat.S_ISDIR(p.lstat().st_mode)
    except OSError:
        return False


def user_caches(home, deadline=None):
    root = Path(home) / "Library/Caches"
    out = []
    try:
        children = sorted(root.iterdir())
    except OSError:
        return out
    for p in children:
        if p.name.startswith("com.apple.") or is_sensitive(p.name) or not _is_dir(p):
            continue
        leftover = p.name.lower().endswith(UPDATE_LEFTOVER)
        out.append(_item(p, home, "update-leftover" if leftover else "cache",
                         "업데이트 잔여물" if leftover else "앱 캐시", deadline))
    return out


def app_caches(home, deadline=None):
    root = Path(home) / "Library/Application Support"
    out, seen = [], set()
    try:
        apps = sorted(root.iterdir())
    except OSError:
        return out
    for app in apps:
        if _skip_dir(app.name) or not _is_dir(app):
            continue
        for pattern in APP_CACHE_GLOBS:
            for p in sorted(app.glob(pattern)):
                # glob 경로 안에 링크가 끼어 있으면(앱 폴더 밖으로 나갈 수 있음) 건너뛴다
                inside = os.path.join(os.path.realpath(app), os.path.relpath(p, app))
                if p in seen or not _is_dir(p) or os.path.realpath(p) != inside:
                    continue
                seen.add(p)
                out.append(_item(p, home, "webview-cache", f"{app.name} 웹뷰 캐시", deadline))
    return out


def dev_caches(home, deadline=None):
    return [_item(Path(home) / rel, home, "dev-cache", label, deadline)
            for rel, label in DEV_CACHES if _is_dir(Path(home) / rel)]


def sqlite_header(path):
    """(page_size, freelist_pages) 또는 None. 헤더 100바이트만 읽는다."""
    try:
        with open(path, "rb") as f:
            h = f.read(100)
    except OSError:
        return None
    if len(h) < 100 or not h.startswith(SQLITE_MAGIC):
        return None
    page = int.from_bytes(h[16:18], "big")
    page = 65536 if page == 1 else page
    return page, int.from_bytes(h[36:40], "big")


def sqlite_free(home, min_free=SQLITE_MIN_FREE, depth=4, deadline=None):
    roots = [(Path(home) / "Library/Application Support", True), (Path(home) / ".ro", False)]
    out = []
    for root, filtered in roots:
        stack = [(root, 0)]
        while stack:
            if deadline is not None and time.monotonic() > deadline:
                break
            d, level = stack.pop()
            try:
                entries = list(os.scandir(d))
            except OSError:
                continue
            for e in entries:
                if is_sensitive(e.name) or (filtered and level == 0 and _skip_dir(e.name)):
                    continue
                try:
                    st = e.stat(follow_symlinks=False)
                except OSError:
                    continue
                if stat.S_ISDIR(st.st_mode) and level < depth:
                    stack.append((e.path, level + 1))
                elif stat.S_ISREG(st.st_mode) and e.name.lower().endswith(SQLITE_EXT):
                    hdr = sqlite_header(e.path)
                    if hdr and hdr[0] * hdr[1] >= min_free:
                        wal = os.path.exists(e.path + "-wal")
                        out.append({"path": e.path, "display": _display(e.path, home), "kind": "sqlite-free",
                                    "label": "SQLite 빈 페이지" + (" (WAL, 추정)" if wal else ""),
                                    "bytes": hdr[0] * hdr[1], "db_bytes": st.st_size, "wal": wal,
                                    "own": not filtered})
    return out


def _mdls(paths, runner=subprocess.run):
    """앱마다 (마지막 사용 원문, Spotlight 물리 크기 원문). 한 번의 mdls 호출로 읽는다."""
    if not paths:
        return []
    try:
        r = runner(["mdls", "-raw", "-name", "kMDItemLastUsedDate", "-name", "kMDItemPhysicalSize", *paths],
                   capture_output=True, timeout=60)
    except (OSError, subprocess.TimeoutExpired):
        return [(None, None)] * len(paths)
    vals = r.stdout.decode("utf-8", "replace").split("\0") if r.returncode == 0 else []
    if len(vals) < 2 * len(paths):
        return [(None, None)] * len(paths)
    return [(vals[2 * i], vals[2 * i + 1]) for i in range(len(paths))]


def applications(app_dir="/Applications", now=None, runner=subprocess.run):
    now = now or datetime.now(timezone.utc)
    try:
        apps = sorted(p for p in Path(app_dir).iterdir() if p.suffix == ".app" and not p.is_symlink())
    except OSError:
        return []
    out = []
    for p, (used, size) in zip(apps, _mdls([str(p) for p in apps], runner)):
        status, days = "unknown", None
        if used == "(null)":
            status = "never_recorded"
        elif used:
            try:
                days = (now - datetime.strptime(used.strip(), "%Y-%m-%d %H:%M:%S %z")).days
                status = "used"
            except ValueError:
                pass
        out.append({"path": str(p), "display": p.name, "kind": "app", "label": "앱",
                    "bytes": int(size) if size and size.strip().isdigit() else None,
                    "last_used": status, "days_since_use": days,
                    "stale": status == "never_recorded" or (days is not None and days > STALE_DAYS)})
    return out


def audit(home=None, app_dir="/Applications", budget=60.0, min_bytes=MIN_BYTES, apps=True, runner=subprocess.run):
    home = Path(home or Path.home())
    deadline = time.monotonic() + budget
    disk = shutil.disk_usage(home)
    caches = user_caches(home, deadline) + app_caches(home, deadline) + dev_caches(home, deadline)
    big = sorted((c for c in caches if c["bytes"] >= min_bytes), key=lambda c: -c["bytes"])
    report = {
        "generated_at": datetime.now().astimezone().isoformat(timespec="seconds"),
        "disk": {"total": disk.total, "free": disk.free},
        "caches": big,
        "cache_total": sum(c["bytes"] for c in caches),
        "small_caches": len(caches) - len(big),
        "sqlite": sorted(sqlite_free(home, deadline=deadline), key=lambda s: -s["bytes"]),
        "apps": applications(app_dir, runner=runner) if apps else [],
        "errors": sum(c["errors"] for c in caches),
        "partial": time.monotonic() > deadline or any(not c["complete"] for c in caches),
    }
    return report


def human(n):
    if n is None:
        return "?"
    n = float(n)
    for unit in ("B", "KB", "MB", "GB"):
        if n < 1024:
            return f"{n:.0f}{unit}" if unit == "B" else f"{n:.1f}{unit}"
        n /= 1024
    return f"{n:.1f}TB"


def render(report, top=10):
    d = report["disk"]
    lines = [f"디스크 여유 {human(d['free'])} / 전체 {human(d['total'])}",
             f"다시 만들어지는 캐시 합계 {human(report['cache_total'])} [추정: 복제 파일 중복 포함]", ""]
    sections = (("앱 캐시 (앱이 다시 만듦)", [c for c in report["caches"] if c["kind"] == "cache"]),
                ("업데이트 잔여물", [c for c in report["caches"] if c["kind"] == "update-leftover"]),
                ("웹뷰 캐시 (Electron 등)", [c for c in report["caches"] if c["kind"] == "webview-cache"]),
                ("개발 도구 캐시 (다시 받거나 빌드해야 함)", [c for c in report["caches"] if c["kind"] == "dev-cache"]),
                ("SQLite 빈 공간 (VACUUM으로 회수 가능)", report["sqlite"]))
    for title, items in sections:
        if not items:
            continue
        lines.append(f"## {title}")
        for c in items[:top]:
            note = "" if c.get("complete", True) else "  (시간 초과, 일부만 셈)"
            own = "  (ro 자체 색인 — 정리 대상 아님)" if c.get("own") else ""
            lines.append(f"  {human(c['bytes']):>8}  {c['display']}{note}{own}")
        if len(items) > top:
            lines.append(f"  … 외 {len(items) - top}개")
        lines.append("")
    stale = [a for a in report["apps"] if a["stale"]]
    if stale:
        lines.append(f"## {STALE_DAYS}일 넘게 안 쓴 앱·사용 기록이 없는 앱 (참고용)")
        lines.append("  기록 없음은 안 썼다는 뜻이 아닐 수 있습니다(Spotlight가 실행을 기록하지 않은 앱도 많음).")
        for a in sorted(stale, key=lambda a: -(a["bytes"] or 0))[:top]:
            when = "기록 없음" if a["last_used"] == "never_recorded" else f"마지막 사용 {a['days_since_use']}일 전"
            lines.append(f"  {human(a['bytes']):>8}  {a['display']}  ({when})")
        lines.append("")
    if report["small_caches"]:
        lines.append(f"10MB 미만 캐시 {report['small_caches']}개는 생략했습니다.")
    if report["errors"]:
        lines.append(f"읽지 못한 항목 {report['errors']}개(권한)는 크기에 빠져 있습니다.")
    if report["partial"]:
        lines.append("시간 예산을 넘겨 일부만 셌습니다. --budget을 늘려 다시 실행하세요.")
    lines.append("읽기 전용 감사입니다. 아무것도 지우거나 옮기지 않았습니다.")
    return "\n".join(lines)


# ---------- ro pro: 죽은 빌드 폴더 ----------
BUILD_DIRS = {".venv": "python", "venv": "python", "node_modules": "node"}
REBUILD_MARKERS = {"python": ("pyproject.toml", "setup.py", "Pipfile", "requirements.txt", "requirements-dev.txt",
                              "uv.lock", "poetry.lock"),
                   "node": ("package.json",)}
LOCKS = {"python": ("uv.lock", "poetry.lock", "Pipfile.lock", "requirements.txt"),
         "node": ("package-lock.json", "yarn.lock", "pnpm-lock.yaml", "bun.lockb")}


def _last_touched(project, depth=3):
    """빌드·숨김 폴더를 뺀 프로젝트 파일의 가장 최근 수정 시각."""
    newest = 0.0
    for dp, dirs, files in os.walk(project):
        here = Path(dp)
        d = len(here.relative_to(project).parts)
        dirs[:] = [x for x in dirs if x not in mapper.SKIP_DIRS and x not in BUILD_DIRS
                   and not x.startswith(".") and d < depth]
        for f in files:
            try:
                newest = max(newest, (here / f).lstat().st_mtime)
            except OSError:
                pass
    return newest


def _git_clean(project, runner):
    if not (project / ".git").exists():
        return True
    try:
        r = runner(["git", "-C", str(project), "status", "--porcelain"], capture_output=True, text=True, timeout=10)
    except (OSError, subprocess.TimeoutExpired):
        return False
    return r.returncode == 0 and not r.stdout.strip()


def dead_builds(roots=None, now=None, stale_days=STALE_DAYS, budget=60.0, runner=subprocess.run, min_bytes=MIN_BYTES):
    """읽기 전용. 반환: [{path, project, kind, bytes, idle_days, lock}] 큰 것부터.
    조건: 프로젝트 파일이 stale_days 넘게 안 바뀜 + 다시 만드는 표지(package.json 등) 있음 + git 작업 트리 깨끗함."""
    now = now or time.time()
    deadline = time.monotonic() + budget
    out = []
    for root in roots if roots is not None else mapper.default_roots():
        for project in mapper.find_projects(root):
            if time.monotonic() > deadline:
                return sorted(out, key=lambda x: -x["bytes"])
            for name, kind in BUILD_DIRS.items():
                d = project / name
                if not d.is_dir() or d.is_symlink():
                    continue
                if not any((project / m).exists() for m in REBUILD_MARKERS[kind]):
                    continue  # 다시 만들 방법이 없으면 후보가 아니다
                idle = (now - _last_touched(project)) / 86400
                if idle < stale_days or not _git_clean(project, runner):
                    continue
                size = measure(d, deadline)
                if size["bytes"] < min_bytes:
                    continue
                out.append({"path": str(d), "project": project.name, "kind": kind, "bytes": size["bytes"],
                            "idle_days": int(idle), "lock": any((project / m).exists() for m in LOCKS[kind]),
                            "complete": size["complete"]})
    return sorted(out, key=lambda x: -x["bytes"])


def quarantine_builds(paths, home=config.HOME):
    """승인된 빌드 폴더를 ~/.ro/cleanup/trash/<배치>/로 통째 옮긴다(저널 V2). 반환: (batch, 옮긴 것, 건너뜀)."""
    trash = fsutil.ensure_dir(Path(home).expanduser() / "cleanup" / "trash")
    paths = [Path(p) for p in paths]
    for p in paths:
        if p.name not in BUILD_DIRS or p.is_symlink() or not p.is_dir():
            raise ValueError(f"빌드 폴더가 아님: {p}")
    roots = sorted({str(p.parent) for p in paths}) + [str(trash)]
    moved, skipped = [], []
    with journal.Batch("storage-builds", roots, home, meta={"count": len(paths)}, protect_trees=False) as b:
        box = trash / b.id
        b.mkdir(box)
        for i, p in enumerate(paths, 1):
            try:
                b.move(p, box / f"{i}-{p.parent.name}-{p.name}")
                moved.append(str(p))
            except (journal.JournalError, OSError) as e:
                skipped.append((str(p), str(e)))
    return b.id, moved, skipped
