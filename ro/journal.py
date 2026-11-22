"""저널 V2: 여러 허용 루트에 걸친 파일·폴더 이동을 한 배치로 기록하고, 역순으로 되돌린다.

ro organize의 기존 저널(파일 단위·한 루트)은 그대로 두고, `ro pro`의 용량 정리·폴더 정리가 이것을 쓴다.

- 연산: mkdir · move(파일·폴더·패키지 통째) · move_dir_contents · rmdir_if_empty
- 모든 연산은 "의도(intent)"를 먼저 디스크에 쓰고(fsync), 실행한 뒤 "완료(done)"를 쓴다. 배치 끝에 "commit".
- commit이 없는 배치(중단·크래시)는 recover()가 파일 상태를 보고 실제로 된 연산만 역순으로 되돌린다.
- 이동은 rename만 쓴다. 다른 볼륨(EXDEV)·iCloud에만 있는 파일(EDEADLK)은 복사하지 않고 그 연산을 거부한다.
- 되돌릴 때는 옮긴 것의 (dev, ino)가 그대로인지 확인한다. 그사이 다른 것으로 바뀌었으면 건드리지 않는다.
- 삭제 연산은 없다. 지우는 일은 사용자가 터미널에서 한다.
"""
import errno
import json
import os
import secrets
import time
from pathlib import Path

from . import config, fsguard, fsutil

FILE = "journal/v2.jsonl"


class JournalError(Exception):
    pass


def _path(home):
    return Path(home).expanduser() / FILE


def _write(home, entry):
    p = _path(home)
    fsutil.ensure_dir(p.parent)
    fd = os.open(p, os.O_WRONLY | os.O_APPEND | os.O_CREAT, 0o600)
    try:
        os.write(fd, (json.dumps(entry, ensure_ascii=False) + "\n").encode("utf-8"))
        os.fsync(fd)
    finally:
        os.close(fd)


def read(home=config.HOME):
    try:
        lines = _path(home).read_text(encoding="utf-8").splitlines()
    except OSError:
        return []
    out = []
    for line in lines:
        try:
            e = json.loads(line)
        except json.JSONDecodeError:
            continue
        # 객체가 아니거나 연산 이름이 없는 줄도 손상 줄이다. 한 줄 때문에 복구 전체가 멈추지 않게 건너뛴다(RO-AUD-103)
        if isinstance(e, dict) and isinstance(e.get("op"), str):
            out.append(e)
    return out


def _inside(path, roots):
    p = os.path.realpath(path)
    return any(p == r or p.startswith(r + os.sep) for r in roots)


class Batch:
    """with journal.Batch(kind, roots, home) as b: b.mkdir(...); b.move(...)  → 정상 종료 시 commit."""

    def __init__(self, kind, roots, home=config.HOME, meta=None, protect_trees=True, learn=False):
        home_dir = os.path.realpath(Path.home())
        self.roots = []
        for r in roots:
            rp = Path(r).expanduser()
            real = os.path.realpath(rp)
            if rp.is_symlink() or not (real == home_dir or real.startswith(home_dir + os.sep)) or real == home_dir:
                raise JournalError(f"허용 루트는 홈 아래의 실제 폴더여야 합니다: {r}")
            self.roots.append(real)
        self.home, self.kind = home, kind
        self.id = time.strftime("%Y%m%d-%H%M%S-") + secrets.token_hex(3)
        self.seq = 0
        self.meta = meta or {}
        self.protect_trees = protect_trees  # 폴더 구조 정리는 True. 빌드 폴더 격리처럼 구조를 안 바꾸면 False
        self.learn = learn                  # 사용자가 고른 자리로 옮기는 배치면 True(ro pro 학습: 확장자 → 폴더)
        self.placed = []

    def __enter__(self):
        _write(self.home, {"batch": self.id, "op": "begin", "kind": self.kind, "roots": self.roots,
                           "meta": self.meta, "ts": time.time()})
        return self

    def __exit__(self, exc_type, exc, tb):
        if exc_type is None:
            _write(self.home, {"batch": self.id, "op": "commit", "ts": time.time()})
            if self.learn:
                from . import profile
                for dst in self.placed:
                    profile.observe_quiet("ext_home", dst.suffix.lower(), dst.parent, home=self.home)
        else:  # 실패하면 이 배치에서 이미 한 것을 바로 되돌린다
            undo(self.id, self.home)
        return False

    def _check(self, *paths):
        for p in paths:
            if not _inside(Path(p).parent, self.roots):
                raise JournalError(f"허용 루트 밖: {p}")
            if not self.protect_trees:
                continue
            root = max((r for r in self.roots if _inside(Path(p).parent, [r])), key=len)
            for d in (Path(p).parent, *Path(p).parent.parents):  # 허용 루트 안쪽 조상만 본다(~/.vscode 등 무관)
                if fsguard.is_protected_tree(d):
                    raise JournalError(f"구조를 바꾸지 않는 폴더 안: {d}")
                if os.path.realpath(d) == root:
                    break

    def _do(self, op, fn, **args):
        self.seq += 1
        entry = {"batch": self.id, "seq": self.seq, "op": op, **{k: str(v) for k, v in args.items()}}
        _write(self.home, {**entry, "state": "intent"})
        extra = fn() or {}
        _write(self.home, {**entry, **extra, "state": "done"})
        return extra

    def mkdir(self, path):
        path = Path(path)
        self._check(path)
        if path.exists():
            return None  # 이미 있던 폴더는 기록하지 않는다(되돌릴 때 지우면 안 되므로)
        return self._do("mkdir", lambda: path.mkdir(mode=0o700) and None, path=path)

    def move(self, src, dst):
        """src(파일·폴더)를 dst로 rename. dst는 없어야 한다(대소문자만 다른 이름 포함)."""
        src, dst = Path(src), Path(dst)
        self._check(src, dst)
        st = src.lstat()
        if src.is_symlink():
            raise JournalError(f"링크는 옮기지 않음: {src}")
        if fsguard.is_dataless(src, st):
            raise JournalError(f"iCloud에만 있음: {src}")
        if not src.is_dir() and fsguard.has_lock_sibling(src):
            raise JournalError(f"편집 중: {src}")

        def run():
            fsguard.reserve(dst)  # 자리를 먼저 배타적으로 잡는다
            try:
                os.replace(src, dst) if not src.is_dir() else _replace_dir(src, dst)
            except OSError as e:
                try:
                    os.unlink(dst)
                except OSError:
                    pass
                why = {errno.EXDEV: "다른 볼륨", errno.EDEADLK: "iCloud에만 있음"}.get(e.errno, e.strerror)
                raise JournalError(f"옮기지 못함({why}): {src}") from None
            return {"dev": st.st_dev, "ino": st.st_ino}
        out = self._do("move", run, src=src, dst=dst)
        if not src.is_dir() and dst.suffix and not dst.is_dir():
            self.placed.append(dst)
        return out

    def move_dir_contents(self, src_dir, dst_dir):
        """src_dir 안의 항목을 dst_dir로 하나씩 옮긴다(각각 기록). 숨김 파일도 함께 옮긴다."""
        src_dir, dst_dir = Path(src_dir), Path(dst_dir)
        self.mkdir(dst_dir)
        for child in sorted(src_dir.iterdir()):
            self.move(child, dst_dir / child.name)

    def rmdir_if_empty(self, path):
        path = Path(path)
        self._check(path)
        if not path.is_dir() or any(path.iterdir()):
            return None
        return self._do("rmdir", lambda: path.rmdir() and None, path=path)


def _replace_dir(src, dst):
    # reserve가 만든 빈 자리 파일을 지우고 폴더를 rename한다(rename은 빈 파일 위에 폴더를 놓지 못한다)
    os.unlink(dst)
    os.rename(src, dst)


def _ops(entries, batch):
    """실제로 된 연산 목록(순서대로): 완료(done) 기록이 있거나, 의도만 있지만 파일 상태로 보아 된 것."""
    states = {}
    for e in entries:
        if e.get("batch") != batch or "seq" not in e:
            continue
        if e["state"] == "done":
            states[e["seq"]] = (e, True)
        else:
            states.setdefault(e["seq"], (e, False))
    out = []
    for _, (e, done) in sorted(states.items()):
        if done or _happened(e):
            out.append(e)
        elif e["op"] == "move":
            _drop_placeholder(e)
    return out


def _happened(e):
    if e["op"] == "mkdir":
        return Path(e["path"]).is_dir()
    if e["op"] == "rmdir":
        return not os.path.lexists(e["path"])
    if e["op"] == "move":
        return not os.path.lexists(e["src"]) and os.path.lexists(e["dst"])
    return False


def _drop_placeholder(e):
    """자리만 잡고 옮기기 전에 멈췄다면 빈 자리 표시 파일을 치운다."""
    d = Path(e["dst"])
    try:
        if os.path.lexists(e["src"]) and d.is_file() and not d.is_symlink() and d.stat().st_size == 0:
            d.unlink()
    except OSError:
        pass


def batches(home=config.HOME):
    """{batch: {"kind", "committed", "undone", "ts"}} 시간 순."""
    out = {}
    for e in read(home):
        b = e.get("batch")
        if e["op"] == "begin":
            out[b] = {"kind": e.get("kind"), "committed": False, "undone": False, "ts": e.get("ts"),
                      "meta": e.get("meta", {})}
        elif b in out and e["op"] == "commit":
            out[b]["committed"] = True
        elif b in out and e["op"] == "undone":
            out[b]["undone"] = True
    return out


def undo(batch=None, home=config.HOME):
    """배치(기본: 되돌리지 않은 가장 최근 배치)를 역순으로 되돌린다. 반환: (batch, 되돌린 수, 건너뜀 목록)."""
    all_b = batches(home)
    if batch is None:
        live = [b for b, v in all_b.items() if not v["undone"]]
        if not live:
            raise JournalError("되돌릴 배치가 없습니다")
        batch = live[-1]
    elif batch not in all_b or all_b[batch]["undone"]:
        raise JournalError(f"되돌릴 수 없는 배치: {batch}")
    restored, skipped = 0, []
    for e in reversed(_ops(read(home), batch)):
        try:
            if e["op"] == "move":
                dst, src = Path(e["dst"]), Path(e["src"])
                st = dst.lstat()
                if "ino" in e and (str(st.st_dev), str(st.st_ino)) != (str(e["dev"]), str(e["ino"])):
                    raise JournalError("옮긴 뒤 다른 것으로 바뀜")
                if os.path.lexists(src):
                    raise JournalError("원래 자리에 다른 것이 생김")
                os.rename(dst, src)
            elif e["op"] == "mkdir":
                Path(e["path"]).rmdir()   # 비어 있지 않으면 OSError → 건너뜀
            elif e["op"] == "rmdir":
                Path(e["path"]).mkdir(mode=0o700)
            restored += 1
        except (OSError, JournalError) as ex:
            skipped.append((e.get("src") or e.get("path"), str(ex)))
    _write(home, {"batch": batch, "op": "undone", "restored": restored, "skipped": len(skipped), "ts": time.time()})
    return batch, restored, skipped


def recover(home=config.HOME):
    """commit도 undone도 없는 배치(중단·크래시)를 찾아 되돌린다. 반환: [(batch, 되돌린 수, 건너뜀)]."""
    return [undo(b, home) for b, v in batches(home).items() if not v["committed"] and not v["undone"]]
