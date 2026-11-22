"""파일을 건드리기 전에 거르는 공용 안전 가드. 읽기만 하고 아무것도 바꾸지 않는다.

- iCloud에만 있는(dataless) 파일: 열지도, 해시하지도, 복사하지도 않는다.
  1차는 SF_DATALESS·`.icloud` 이름 선검사, 2차는 프로세스 진입 시 커널 물질화 차단(setiopolicy_np OFF).
  OFF 아래에서 dataless를 읽거나 iCloud 밖으로 옮기면 EDEADLK로 즉시 실패하고 내려받기는 0이다
  (docs/POKE-M0-REPORT.md §6, 2026-11-16 실측).
- macOS 패키지(.pages·.app 등)는 폴더처럼 보여도 하나의 파일로 다룬다. 안으로 들어가지 않는다.
- 편집 중으로 보이는 파일(잠금 파일 짝·최근 수정)과 쓸 수 없는 파일은 보류한다.
"""
import ctypes
import errno
import os
import stat
import sys
import time
import unicodedata
from pathlib import Path
from urllib.parse import unquote

SF_DATALESS = 0x40000000
DATALESS_CONFIDENCE_CAP = 0.75   # 본문을 못 읽고 메타만으로 판단한 제안의 확신 상한

IOPOL_TYPE_VFS_MATERIALIZE_DATALESS_FILES = 3
IOPOL_SCOPE_PROCESS = 0
IOPOL_MATERIALIZE_DATALESS_FILES_OFF = 1

# NSWorkspace.isFilePackage가 참인 흔한 형식. Python에는 그 API가 없어 확장자와 번들 구조로 판정한다.
PACKAGE_EXTS = frozenset((
    ".pages", ".numbers", ".key", ".rtfd", ".app", ".xcodeproj", ".xcworkspace", ".playground",
    ".photoslibrary", ".musiclibrary", ".band", ".logicx", ".fcpbundle", ".framework", ".bundle",
    ".vmwarevm", ".sparsebundle",
))
# 이 표지가 든 폴더는 사용자가 도구로 구조를 관리한다. 구조를 바꾸지 않는다.
PROTECTED_MARKERS = (".obsidian", ".vscode")
RECENT_EDIT_SECONDS = 120
EDGE_EXCLUSIVE = os.O_WRONLY | os.O_CREAT | os.O_EXCL


# ---------- 커널 물질화 차단 ----------
def _libc():
    if sys.platform != "darwin":
        return None
    try:
        return ctypes.CDLL(None, use_errno=True)
    except OSError:
        return None


def materialization_policy():
    """현재 프로세스의 dataless 물질화 정책. 1=OFF(차단). macOS가 아니면 None."""
    libc = _libc()
    if libc is None:
        return None
    return libc.getiopolicy_np(IOPOL_TYPE_VFS_MATERIALIZE_DATALESS_FILES, IOPOL_SCOPE_PROCESS)


def disable_materialization():
    """이 프로세스(와 이후 자식)가 iCloud 파일을 몰래 내려받지 못하게 한다. 반환: 적용 뒤 정책값."""
    libc = _libc()
    if libc is None:
        return None
    libc.setiopolicy_np(IOPOL_TYPE_VFS_MATERIALIZE_DATALESS_FILES, IOPOL_SCOPE_PROCESS,
                        IOPOL_MATERIALIZE_DATALESS_FILES_OFF)
    return materialization_policy()


# ---------- 판정 ----------
def _st(path_or_st):
    if isinstance(path_or_st, os.stat_result):
        return path_or_st
    try:
        return os.lstat(path_or_st)
    except OSError:
        return None


def is_dataless(path, st=None):
    """iCloud에만 있고 이 Mac에 내용이 없는 파일. 옛 방식 자리표시(`.이름.icloud`)도 포함한다."""
    name = Path(path).name
    if name.startswith(".") and name.endswith(".icloud"):
        return True
    st = st or _st(path)
    return bool(st and getattr(st, "st_flags", 0) & SF_DATALESS)


def is_package(path, st=None):
    """폴더지만 하나의 문서·앱으로 다뤄야 하는 것."""
    p = Path(path)
    st = st or _st(p)
    if not st or not stat.S_ISDIR(st.st_mode):
        return False
    if p.suffix.lower() in PACKAGE_EXTS:
        return True
    return bool(p.suffix) and (p / "Contents" / "Info.plist").is_file()


def is_protected_tree(directory):
    """구조를 바꾸면 안 되는 폴더(.obsidian·.vscode 보유)."""
    d = Path(directory)
    return any((d / m).exists() for m in PROTECTED_MARKERS)


def is_lock_file(name):
    """Office·LibreOffice가 편집 중에 만드는 잠금 파일."""
    return name.startswith("~$") or (name.startswith(".~lock.") and name.endswith("#"))


def has_lock_sibling(path):
    """옆에 이 파일의 잠금 파일이 있으면 지금 열려 있다."""
    p = Path(path)
    return any(c.exists() for c in (p.with_name("~$" + p.name), p.with_name("~$" + p.name[2:]),
                                    p.with_name(f".~lock.{p.name}#")))


def recently_modified(st, now=None, window=RECENT_EDIT_SECONDS):
    now = time.time() if now is None else now
    return now - st.st_mtime < window


def name_key(name):
    """비교용 이름 키: URL 인코딩을 풀고 NFC로 맞춘 뒤 대소문자를 접는다. 실제 이동에는 원래 경로를 쓴다."""
    return unicodedata.normalize("NFC", unquote(str(name))).casefold()


def hold_reason(path, st=None, now=None, recent_window=RECENT_EDIT_SECONDS):
    """이 파일을 지금 옮기거나 열면 안 되는 이유. 없으면 None."""
    p = Path(path)
    st = st or _st(p)
    if st is None:
        return "없음"
    if stat.S_ISLNK(st.st_mode):
        return "링크"
    if is_dataless(p, st):
        return "iCloud에만 있음"
    if is_lock_file(p.name):
        return "잠금 파일"
    if has_lock_sibling(p):
        return "편집 중"
    if recent_window and recently_modified(st, now, recent_window):
        return "방금 바뀜"
    if not os.access(p, os.W_OK) or not os.access(p.parent, os.W_OK):
        return "쓰기 권한 없음"
    return None


# ---------- 순회 ----------
def walk(root, skip_dirs=(), max_depth=None, hidden=False, onerror=None):
    """(경로, lstat, 종류) 생성. 종류는 "file" 또는 "package"(안으로 들어가지 않는 하나의 항목).

    심볼릭 링크는 따라가지도 내보내지도 않는다. 숨김 이름과 skip_dirs는 들어가지 않는다.
    dataless 여부는 거르지 않는다(이름·메타는 쓸모 있으니). 내용을 읽기 전에 is_dataless로 확인한다.
    """
    root = Path(root)
    base_depth = len(root.parts)
    for dp, dirs, files in os.walk(root, onerror=onerror):
        here = Path(dp)
        depth = len(here.parts) - base_depth
        keep = []
        for d in dirs:
            if d in skip_dirs or (not hidden and d.startswith(".")):
                continue
            p = here / d
            st = _st(p)
            if st is None or stat.S_ISLNK(st.st_mode):
                continue
            if is_package(p, st):
                yield p, st, "package"
                continue
            if max_depth is None or depth < max_depth:
                keep.append(d)
        dirs[:] = keep
        for f in files:
            if not hidden and f.startswith("."):
                continue
            p = here / f
            st = _st(p)
            if st is None or stat.S_ISLNK(st.st_mode) or not stat.S_ISREG(st.st_mode):
                continue
            yield p, st, "file"


# ---------- 원자적 자리 잡기 ----------
def reserve(dst):
    """목적지에 빈 자리 표시 파일을 배타적으로 만든다. 이미 있으면 FileExistsError(대소문자만 다른 이름 포함)."""
    dst = Path(dst)
    try:
        for e in os.scandir(dst.parent):
            if e.name != dst.name and name_key(e.name) == name_key(dst.name):
                raise FileExistsError(errno.EEXIST, "대소문자·정규화만 다른 같은 이름이 있음", str(dst))
    except FileNotFoundError:
        pass
    os.close(os.open(dst, EDGE_EXCLUSIVE, 0o600))
    return dst
