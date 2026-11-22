"""ro pro 먼저 다가가기 상황 판단(V2.1 §6.1). 읽기 전용이다: 메타(lstat)만 보고 파일을 열거나 옮기지 않는다.

- dmg_installed  Downloads의 .dmg/.pkg와 이름이 맞는 앱이 그 뒤에 /Applications에 생겼다 → 설치 파일 격리 1건
- disk_low       시동 디스크 여유가 15GB 아래 → C안 카드(죽은 빌드 폴더·남은 설치 파일·iCloud 로컬 사본)
- old_version    앞 창에서 연 문서 옆에 더 새 판(v3·final·최종)이 있다 → 새 판 위치 보기
- find_lost      Finder에서 2분 안에 폴더를 4번 넘게 오갔다 → 파일 찾기 열기
실제로 옮기는 일은 staging 카드에서 사용자가 고른 것만 저널 배치로 한다. 신뢰 단계(수락 − 되돌림)가 낮으면
구조를 바꾸는 카드는 열지 않는다.
"""
import os
import re
import shutil
import time
import unicodedata
from collections import deque
from pathlib import Path

from . import designmetrics, detect, fsguard, log

DISK_LOW = 15 * 1024 ** 3
INSTALLER_EXTS = (".dmg", ".pkg")
INSTALL_SETTLE = 10 * 60          # 내려받은 지 10분은 지나야 설치가 끝났다고 본다
EVICT_MIN = 100 * 1024 ** 2       # iCloud 로컬 사본 후보 최소 크기
EVICT_IDLE_DAYS = 60
SEEK_WINDOW = 120
SEEK_SWITCHES = 4
TRUST_STEPS = (5, 15)             # 수락 − 되돌림 ≥5 → 2단계(묶음·새 폴더), ≥15 → 3단계(합치기·쪼개기)
ICLOUD = "~/Library/Mobile Documents/com~apple~CloudDocs"
_NOISE = re.compile(r"[\s._\-()]+(v?\d+(\.\d+)*|arm64|x64|x86_64|intel|universal|mac(os)?|osx|setup|installer|"
                    r"darwin|aarch64|amd64|latest|stable|beta)\b", re.I)


# ---- 신뢰 3단계 ----
def trust(log_dir=log.LOG_DIR, now=None):
    """(단계 1~3, 점수). 점수 = 수락 − 되돌림(30일)."""
    now = time.time() if now is None else now
    acts = [e["data"].get("action") for e in designmetrics._events(log_dir, now - 30 * 86400)
            if e["kind"] == designmetrics.NUDGE]
    score = acts.count("accepted") - acts.count("undone")
    return 1 + sum(score >= s for s in TRUST_STEPS), score


STAGE_OPS = {1: {"quarantine", "evict", "reveal"}, 2: {"move", "mkdir"}, 3: {"merge", "split"}}


def allowed_ops(stage):
    return set().union(*(STAGE_OPS[s] for s in range(1, stage + 1)))


# ---- 설치 파일 ----
def _norm(name):
    s = unicodedata.normalize("NFC", name).casefold()
    prev = None
    while prev != s:
        prev, s = s, _NOISE.sub("", s)
    return re.sub(r"[^0-9a-z가-힣]+", "", s)


def _app_installed_at(app_path, st):
    """DMG에서 끌어다 놓은 앱은 번들 디렉터리 mtime이 빌드 날짜로 남지만 Info.plist·birthtime은 설치 시각에 찍힌다."""
    ts = max(st.st_mtime, getattr(st, "st_birthtime", 0.0))
    plist = Path(app_path) / "Contents" / "Info.plist"
    try:
        pst = plist.stat()
        ts = max(ts, pst.st_mtime, getattr(pst, "st_birthtime", 0.0))
    except OSError:
        pass
    return ts


def installed_installers(downloads="~/Downloads", app_dirs=("/Applications", "~/Applications"), now=None):
    """[{path, app}] 설치가 끝난 것으로 보이는 설치 파일. 이름 맞는 앱이 설치 파일보다 나중에 바뀌었을 때만."""
    now = time.time() if now is None else now
    apps = []
    for d in app_dirs:
        base = Path(d).expanduser()
        try:
            for e in os.scandir(base):
                if e.name.endswith(".app"):
                    st = e.stat(follow_symlinks=False)
                    apps.append((_norm(e.name[:-4]), e.name, _app_installed_at(e.path, st)))
        except OSError:
            continue
    out = []
    try:
        entries = list(os.scandir(Path(downloads).expanduser()))
    except OSError:
        return out
    for e in entries:
        if not e.name.lower().endswith(INSTALLER_EXTS) or e.name.startswith("."):
            continue
        p = Path(e.path)
        st = e.stat(follow_symlinks=False)
        if fsguard.is_dataless(p, st) or fsguard.is_lock_file(p.name) or now - st.st_mtime < INSTALL_SETTLE:
            continue
        key = _norm(p.stem)
        if len(key) < 3:
            continue
        hit = next((name for k, name, mt in apps if len(k) >= 3 and (key.startswith(k) or k.startswith(key))
                    and mt >= st.st_mtime - 60), None)
        if hit:
            out.append({"path": str(p), "app": hit, "bytes": st.st_size})
    return out


# ---- 용량 ----
def free_bytes(path="~"):
    return shutil.disk_usage(Path(path).expanduser()).free


def evict_candidates(root=ICLOUD, now=None, min_bytes=EVICT_MIN, idle_days=EVICT_IDLE_DAYS, limit=20):
    """iCloud Drive에 내려받아진 채 오래 안 쓴 큰 파일(로컬 사본만 내보낼 후보). 메타만 본다."""
    now = time.time() if now is None else now
    base = Path(root).expanduser()
    out = []
    for p, st, kind in fsguard.walk(base) if base.is_dir() else ():
        if kind != "file" or st.st_size < min_bytes or fsguard.is_dataless(p, st) or fsguard.hold_reason(p, st, now):
            continue
        idle = (now - max(st.st_mtime, st.st_atime)) / 86400
        if idle >= idle_days:
            out.append({"path": str(p), "bytes": st.st_size, "idle_days": int(idle)})
    return sorted(out, key=lambda x: -x["bytes"])[:limit]


# ---- 옛 판본 ----
def newer_version(doc):
    """doc 옆에 같은 묶음의 더 새 판이 있으면 그 경로. 이름·메타만 본다(내용을 열지 않는다)."""
    p = Path(doc)
    try:
        files = [(Path(e.path), e.stat(follow_symlinks=False)) for e in os.scandir(p.parent)
                 if e.is_file(follow_symlinks=False) and not e.name.startswith((".", "~$"))]
    except OSError:
        return None
    for (keeper, kst), olds in detect.version_groups(files):
        if any(o == p for o, _ in olds):
            mine = next(st for o, st in olds if o == p)
            if keeper != p and kst.st_mtime >= mine.st_mtime:
                return str(keeper)
    return None


# ---- 찾기 헤맴 ----
class SeekWatch:
    """Finder 창의 폴더가 짧은 시간에 여러 번 바뀌는지만 센다(폴더 경로는 메모리에만, 2분)."""

    def __init__(self):
        self.moves = deque(maxlen=32)

    def on_folder(self, folder, now):
        if self.moves and self.moves[-1][0] == folder:
            return None
        self.moves.append((folder, now))
        recent = [(f, t) for f, t in self.moves if now - t <= SEEK_WINDOW]
        if len(recent) > SEEK_SWITCHES and len({f for f, _ in recent}) >= 2:
            self.moves.clear()
            return {"switches": len(recent) - 1, "folders": len({f for f, _ in recent}), "last": folder}
        return None


# ---- 풀린 압축 원본 & 중복 다운로드 (읽기 전용) ----
ARCHIVE_EXTS = (".zip",)
REVIEW_KEYWORDS = ("계약", "영수증", "세금", "급여", "연봉", "invoice", "contract", "receipt", "tax", "payroll")
DUP_MAX_BYTES = 100 * 1024 * 1024  # 백그라운드 중복 감지는 100MB 이하 파일만 해시한다
DUP_MAX_FILES = 200


def unpacked_archives(downloads="~/Downloads", now=None):
    """[{path, extracted, bytes}] 같은 폴더 안에 이미 같은 이름의 폴더로 압축이 풀려 있는 .zip 원본(읽기 전용)."""
    now = time.time() if now is None else now
    base = Path(downloads).expanduser()
    try:
        entries = list(os.scandir(base))
    except OSError:
        return []
    dirs = { _norm(e.name): e.name for e in entries if e.is_dir(follow_symlinks=False) and not e.name.startswith(".") }
    out = []
    for e in entries:
        if not e.name.lower().endswith(ARCHIVE_EXTS) or e.name.startswith("."):
            continue
        p = Path(e.path)
        try:
            st = e.stat(follow_symlinks=False)
        except OSError:
            continue
        if fsguard.is_dataless(p, st) or fsguard.is_lock_file(p.name) or now - st.st_mtime < INSTALL_SETTLE:
            continue
        key = _norm(p.stem)
        if len(key) >= 3 and key in dirs:
            out.append({"path": str(p), "extracted": dirs[key], "bytes": st.st_size})
    return out


def duplicate_downloads(downloads="~/Downloads", now=None):
    """[{path, original, bytes}] 다운로드 폴더 안의 바이트 동일 중복 사본(재무·계약 민감 파일 제외, 읽기 전용)."""
    now = time.time() if now is None else now
    base = Path(downloads).expanduser()
    try:
        entries = list(os.scandir(base))
    except OSError:
        return []
    files = []
    for e in entries:
        if e.name.startswith(".") or not e.is_file(follow_symlinks=False):
            continue
        p = Path(e.path)
        try:
            st = e.stat(follow_symlinks=False)
        except OSError:
            continue
        if st.st_size <= 0 or st.st_size > DUP_MAX_BYTES or fsguard.is_dataless(p, st) or fsguard.is_lock_file(p.name) or now - st.st_mtime < INSTALL_SETTLE:
            continue
        lower = p.name.casefold()
        if any(k in lower for k in REVIEW_KEYWORDS):
            continue
        files.append((p, st))
        if len(files) >= DUP_MAX_FILES:
            break
    out = []
    for keeper, dups, _sha in detect.duplicate_groups(files):
        for dup, dst in dups:
            out.append({"path": str(dup), "original": keeper.name, "bytes": dst.st_size})
    return out


# ---- AI 도구 작업 전환 감지 ----
AI_TOOL_ALIASES = {
    "claude": "Claude",
    "claude code": "Claude",
    "codex": "Codex",
    "antigravity": "Antigravity",
    "cursor": "Cursor",
}
SWITCH_WINDOW = 300.0


def _ai_tool_name(app_name):
    s = (app_name or "").strip().casefold()
    for k, label in AI_TOOL_ALIASES.items():
        if s == k or s.startswith(k + " "):
            return label
    return None


class ContextSwitchWatch:
    """서로 다른 AI 도구로 전환할 때만 감지한다(일반 앱 전환은 무시)."""

    def __init__(self):
        self.last_tool = None
        self.last_at = 0.0

    def on_app(self, app_name, now=None):
        now = time.time() if now is None else now
        tool = _ai_tool_name(app_name)
        if not tool:
            return None
        prev, prev_at = self.last_tool, self.last_at
        self.last_tool, self.last_at = tool, now
        if prev and prev != tool and (now - prev_at) <= SWITCH_WINDOW:
            return {"from": prev, "to": tool}
        return None
