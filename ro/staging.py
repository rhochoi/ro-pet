"""C안 스테이징 카드: 먼저 다가가기가 여는 확인 카드. ro pro 전용.

- 카드는 항목 목록이다. 항목마다 확신(0~1)이 있고, 0.9 이상은 '확실'(접어서 기본 선택), 그 아래는 '아마도요'
  (펼쳐서 기본 해제 — 사용자가 직접 골라야 한다). 메타만 보고 정한 항목(iCloud에만 있음·로컬 사본 내보내기)은
  0.75를 넘지 않는다.
- 적용은 approve=true와 고른 항목 id만 받는다. 이동·격리는 저널 배치 하나(되돌리기 1번)로 한다.
  iCloud 로컬 사본 내보내기(brctl evict)는 파일을 지우지 않고 다시 내려받을 수 있지만 저널로 되돌릴 수 없어서
  따로 세고, 이미 iCloud에만 있거나 편집 중이면 건너뛴다.
- 신뢰 단계가 허용하지 않는 동작이 든 카드는 만들지 않는다(scenarios.allowed_ops).
"""
import os
import secrets
import subprocess
import time
from pathlib import Path

from . import config, designmetrics, fsguard, fsutil, journal, log, scenarios

SURE = 0.9
META_CAP = 0.75
CARD_TTL = 30 * 60
OPEN_DOC_HOLD = 30 * 60   # 앞 창에서 열려 있던 문서(AXDocument)는 이만큼 옮기지 않는다
MAX_ITEMS = 50


class StageError(Exception):
    pass


def item(op, path, confidence, reason, dest=None, size=None, dest_name=None):
    if op not in ("quarantine", "evict", "move"):
        raise StageError(f"모르는 동작: {op}")
    if op == "evict":
        confidence = min(confidence, META_CAP)
    return {"op": op, "path": str(path), "dest": str(dest) if dest else None,
            "dest_name": str(dest_name) if dest_name else None, "bytes": size,
            "confidence": round(float(confidence), 2), "reason": reason}


class Stage:
    """카드 보관소(메모리). 경로는 서버만 쥐고 화면에는 이름·크기·이유만 준다."""

    def __init__(self, home=config.HOME, log_dir=log.LOG_DIR, runner=subprocess.run):
        self.home, self.log_dir, self.runner = home, log_dir, runner
        self.cards = {}
        self.open_docs = {}   # 앞 창 문서 경로 → 마지막으로 본 시각(메모리에만)

    def held(self, path, now=None):
        """옮기면 안 되는 이유(열려 있음·편집 중·방금 바뀜·iCloud에만 있음·권한). 없으면 None."""
        now = time.time() if now is None else now
        p = Path(path)
        if now - self.open_docs.get(str(p), -1e18) < OPEN_DOC_HOLD:
            return "열려 있음"
        if p.is_dir() and not p.is_symlink():
            return None if os.access(p.parent, os.W_OK) else "쓰기 권한 없음"
        return fsguard.hold_reason(p, now=now)

    def open(self, kind, trigger, items, roots, title, now=None, proactive=True):
        now = time.time() if now is None else now
        stage, _ = scenarios.trust(self.log_dir, now)
        ops = {it["op"] for it in items}
        allowed = scenarios.allowed_ops(stage) if proactive else (scenarios.allowed_ops(stage) | {"move"})
        if not items or not ops <= allowed:
            raise StageError("아직 이 카드를 열 만큼 믿음이 쌓이지 않았어요")
        items = items[:MAX_ITEMS]
        for i, it in enumerate(items, 1):
            it["id"] = i
            it["sure"] = it["confidence"] >= SURE
        cid = secrets.token_hex(6)
        self.cards = {k: c for k, c in self.cards.items() if now - c["at"] < CARD_TTL}
        self.cards[cid] = {"id": cid, "kind": kind, "trigger": trigger, "title": title, "items": items,
                           "roots": [str(r) for r in roots], "at": now, "batch": None}
        return cid

    def view(self, cid):
        c = self.cards.get(cid)
        if not c:
            return None
        return {"id": c["id"], "kind": c["kind"], "title": c["title"], "applied": c["batch"] is not None,
                "items": [{"id": it["id"], "op": it["op"], "name": Path(it["path"]).name,
                           "dest": Path(it["dest"]).name if it["dest"] else None, "bytes": it["bytes"],
                           "confidence": it["confidence"], "sure": it["sure"], "reason": it["reason"]}
                          for it in c["items"]]}

    def apply(self, cid, picks, approve=False):
        """고른 항목만 한다. 반환: {batch, moved, evicted, skipped}."""
        c = self.cards.get(cid)
        if approve is not True:
            raise StageError("승인 없이 옮기지 않아요")
        if not c or c["batch"] is not None:
            raise StageError("카드가 없거나 이미 적용했어요")
        if not isinstance(picks, list) or not picks or any(type(p) is not int for p in picks):
            raise StageError("고른 항목이 없어요")
        chosen = [it for it in c["items"] if it["id"] in set(picks)]
        if len(chosen) != len(set(picks)):
            raise StageError("모르는 항목이 있어요")
        moved, evicted, skipped = [], [], []
        trash = fsutil.ensure_dir(Path(self.home).expanduser() / "cleanup" / "trash")
        files = [it for it in chosen if it["op"] in ("quarantine", "move")]
        batch_id = None
        if files:
            roots = sorted(set(c["roots"]) | {str(trash)})
            moving = any(it["op"] == "move" for it in files)   # 구조 보호(.obsidian 등)는 자리를 바꾸는 이동에만
            with journal.Batch(f"stage-{c['kind']}", roots, self.home, meta={"count": len(files)},
                               protect_trees=moving, learn=moving) as b:
                batch_id = b.id
                box = trash / b.id
                for it in files:
                    src = Path(it["path"])
                    why = self.held(src)
                    if why:
                        skipped.append((it["id"], why))
                        continue
                    try:
                        if it["op"] == "quarantine":
                            b.mkdir(box)
                            b.move(src, box / f"{it['id']}-{src.name}")
                        else:
                            dest_dir = Path(it["dest"])
                            # 허용 루트 안의 없는 중간 폴더를 위에서부터 차례로 만들어야 undo 시 역순 rmdir로 깔끔히 지워진다
                            missing_dirs = []
                            cur = dest_dir
                            while not cur.exists() and cur != cur.parent:
                                missing_dirs.append(cur)
                                cur = cur.parent
                            for md in reversed(missing_dirs):
                                b.mkdir(md)
                            target_name = it.get("dest_name") or src.name
                            b.move(src, dest_dir / target_name)
                        moved.append(it["id"])
                    except (journal.JournalError, OSError) as e:
                        skipped.append((it["id"], str(e)))
        for it in (x for x in chosen if x["op"] == "evict"):
            p = Path(it["path"])
            why = None if p.exists() else "없음"
            why = why or ("이미 iCloud에만 있음" if fsguard.is_dataless(p) else self.held(p))
            if why:
                skipped.append((it["id"], why))
                continue
            try:
                r = self.runner(["brctl", "evict", str(p)], capture_output=True, text=True, timeout=30)
                ok = r.returncode == 0
            except (OSError, subprocess.TimeoutExpired):
                ok = False
            (evicted.append(it["id"]) if ok else skipped.append((it["id"], "내보내지 못함")))
        c["batch"] = batch_id or "evict-only"
        c["moved"] = moved
        log.append("stage", f"{c['kind']} 적용 {len(moved)}건, 로컬 사본 {len(evicted)}건",
                   {"kind": c["kind"], "batch": batch_id, "moved": len(moved), "evicted": len(evicted),
                    "skipped": len(skipped)}, log_dir=self.log_dir)
        return {"batch": batch_id, "moved": moved, "evicted": evicted, "skipped": skipped}

    def undo(self, cid):
        c = self.cards.get(cid)
        if not c or not c["batch"] or c["batch"] == "evict-only":
            raise StageError("되돌릴 배치가 없어요")
        _, restored, skipped = journal.undo(c["batch"], self.home)
        designmetrics.record_nudge(c["trigger"], "undone", batch=c["batch"], log_dir=self.log_dir)
        c["batch"] = None
        files = sum(1 for it in c["items"] if it["id"] in c.get("moved", ()) and Path(it["path"]).exists())
        return {"restored": restored, "files": files, "skipped": skipped}
