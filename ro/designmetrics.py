"""디자인 철학 v2의 관찰 반증 지표(docs/DESIGN-VALIDATION.md 3절). 로컬 로그의 개수·시간만 읽는다.

    python -m ro.designmetrics [--days 30]

파일 이름·경로·요약문은 읽어도 출력하지 않는다.
"""
import argparse
import json
import time
from collections import Counter
from pathlib import Path

from . import log

# 사용자가 ro를 부른 흔적으로 보는 이벤트(펫 패널 열기·찾기는 아직 기록되지 않는다: 계측 공백)
INVOKED = {"organize_scan", "organize", "organize_edit", "tidy", "handoff", "note", "revoke"}
WEEK = 7 * 86400
DAY = 86400

# 원칙 4(개정 2026-11-16): 먼저 다가간 기록. 트리거는 정해진 이름만 쓴다(파일 이름·내용 금지).
NUDGE = "nudge"
NUDGE_ACTIONS = ("shown", "accepted", "off", "ignored", "undone")   # undone: 수락으로 한 일을 되돌림(신뢰 단계)
DEMOTE_MIN, DEMOTE_OFF, DEMOTE_ACCEPT = 30, 0.20, 0.10   # 트리거별 1단계 강등선
REVERT_MIN, REVERT_ACCEPT = 100, 0.10                    # 원칙 4 개정 전으로 되돌리는 선
HELP_TARGET, ANNOY_LIMIT = 0.40, 0.35                    # M5 목표: 유효 도움률·끄기율


def _events(log_dir, since):
    out = []
    for f in sorted(Path(log_dir).expanduser().glob("*.jsonl")):
        for line in f.read_text(encoding="utf-8").splitlines():
            try:
                e = json.loads(line)
                e["t"] = time.mktime(time.strptime(e["ts"][:19], "%Y-%m-%dT%H:%M:%S"))
            except (ValueError, KeyError):
                continue  # 손상된 줄은 건너뛴다(audit가 따로 잡는다)
            if e["t"] >= since:
                out.append(e)
    return out


def compute(log_dir=log.LOG_DIR, days=30, now=None, downloads=None):
    """반환: 지표 dict(개수·비율만)."""
    now = now or time.time()
    events = _events(log_dir, now - days * 86400)
    org = [e for e in events if e["kind"] == "organize"]
    applied = [e for e in org if "categories" in e["data"]]  # 적용 이벤트만 categories를 남긴다
    undone = [e for e in org if "categories" not in e["data"]]
    applied_at = {e["data"].get("batch"): e["t"] for e in applied}
    sums = lambda es, k: sum(e["data"].get(k, 0) for e in es)
    undone_week = [e for e in undone if e["t"] - applied_at.get(e["data"].get("batch"), float("inf")) <= WEEK]
    edits = [e for e in events if e["kind"] == "organize_edit"]
    ratio = lambda a, b: round(a / b, 3) if b else None
    m = {
        "기간(일)": days,
        "원칙2 적용 배치": len(applied),
        "원칙2 ro가 접은 항목": sums(applied, "by_ro"),
        "원칙2 사람이 고른 항목": sums(applied, "by_user"),
        "원칙2 기록 이전 항목": sums(applied, "by_unknown") + sum(
            e["data"].get("count", 0) for e in applied if "by_ro" not in e["data"]),
        "원칙2 7일 안 되돌린 접힌 항목": sums(undone_week, "by_ro"),
        "원칙2 7일 안 되돌린 사람 항목": sums(undone_week, "by_user"),
        "원칙2 ro 제안과 다르게 고른 수정": sum(e["data"].get("from") != e["data"].get("to") for e in edits),
        "원칙2 수정 전체": len(edits),
        "원칙4 ro를 부른 날": len({time.strftime("%Y-%m-%d", time.localtime(e["t"]))
                               for e in events if e["kind"] in INVOKED}),
    }
    m["원칙2 접힌 항목 되돌림 비율"] = ratio(m["원칙2 7일 안 되돌린 접힌 항목"], m["원칙2 ro가 접은 항목"])
    m["원칙2 다르게 고른 비율"] = ratio(m["원칙2 ro 제안과 다르게 고른 수정"], m["원칙2 수정 전체"])
    if downloads is not None:
        d = Path(downloads).expanduser()
        m["원칙4 다운로드 폴더 파일 수"] = sum(1 for p in d.iterdir() if p.is_file()) if d.is_dir() else None
    return m


def record_nudge(trigger, action, batch=None, log_dir=log.LOG_DIR, at=None, level=2, why=None):
    """먼저 다가간 일 하나를 개수용으로 남긴다. batch는 수락이 만든 정리 배치(24시간 안 되돌림을 잇는다).
    level 1(표정)은 따로 세고 강등·상한 판정에는 넣지 않는다."""
    if action not in NUDGE_ACTIONS:
        raise ValueError(f"알 수 없는 동작: {action}")
    data = {"trigger": trigger, "action": action, "level": level}
    if batch:
        data["batch"] = batch
    if why:      # 1단계로 낮춘 이유(정해진 짧은 말만: '입력 중'·'오늘 상한' 등)
        data["why"] = why
    return log.append(NUDGE, f"{trigger} {action}", data, log_dir=log_dir, at=at)


def nudges(log_dir=log.LOG_DIR, days=30, now=None):
    """반환: {트리거: {노출, 수락, 끄기, 무시, 24시간 안 되돌림}} (개수만)."""
    now = now or time.time()
    events = _events(log_dir, now - days * 86400)
    undone_at = {}
    for e in events:
        if e["kind"] == "organize" and "categories" not in e["data"] and e["data"].get("batch"):
            undone_at.setdefault(e["data"]["batch"], e["t"])
    out, last_accept = {}, {}
    for e in events:
        if e["kind"] != NUDGE or e["data"].get("level", 2) != 2:
            continue
        d = e["data"]
        c = out.setdefault(d.get("trigger", "?"), {"노출": 0, "수락": 0, "끄기": 0, "무시": 0, "24시간 안 되돌림": 0})
        key = {"shown": "노출", "accepted": "수락", "off": "끄기", "ignored": "무시"}.get(d.get("action"))
        if key:
            c[key] += 1
        if d.get("action") == "accepted" and 0 <= undone_at.get(d.get("batch"), -1) - e["t"] <= DAY:
            c["24시간 안 되돌림"] += 1
        if d.get("action") == "accepted":
            last_accept[d.get("trigger", "?")] = e["t"]
        elif d.get("action") == "undone" and 0 <= e["t"] - last_accept.get(d.get("trigger", "?"), -1e18) <= DAY:
            c["24시간 안 되돌림"] += 1   # 확인 카드에서 되돌림(수락 뒤 24시간 안)
    return out


def nudge_verdicts(counts):
    """트리거별 강등과 원칙 4 전체 판정. 표본이 모자라면 판정하지 않는다."""
    ratio = lambda a, b: a / b if b else 0.0
    out = {}
    for t, c in sorted(counts.items()):
        if c["노출"] < DEMOTE_MIN:
            out[t] = "표본 부족"
        elif ratio(c["끄기"], c["노출"]) >= DEMOTE_OFF or ratio(c["수락"], c["노출"]) < DEMOTE_ACCEPT:
            out[t] = "1단계로 강등"
        else:
            out[t] = "유지"
    shown = sum(c["노출"] for c in counts.values())
    accepted = sum(c["수락"] for c in counts.values())
    kept = accepted - sum(c["24시간 안 되돌림"] for c in counts.values())
    off = sum(c["끄기"] for c in counts.values())
    if shown < REVERT_MIN:
        out["원칙4 전체"] = "표본 부족"
    elif ratio(accepted, shown) < REVERT_ACCEPT:
        out["원칙4 전체"] = "개정 전으로 되돌리기 검토"
    elif ratio(kept, shown) < HELP_TARGET or ratio(off, shown) >= ANNOY_LIMIT:
        out["원칙4 전체"] = "M5 목표 미달"
    else:
        out["원칙4 전체"] = "통과"
    return out


def kill_switch(log_dir=log.LOG_DIR, days=30, now=None):
    """원칙 4 전체 킬스위치: 2단계 노출 100건 이상에서 수락 < 10%면 모든 트리거를 1단계로만 낸다(M5)."""
    return nudge_verdicts(nudges(log_dir, days, now)).get("원칙4 전체") == "개정 전으로 되돌리기 검토"


def demoted(trigger, log_dir=log.LOG_DIR, days=30, now=None):
    """이 트리거가 2단계(토스트) 자격을 잃었는가."""
    return nudge_verdicts(nudges(log_dir, days, now)).get(trigger) == "1단계로 강등"


def verdicts(m):
    """사전 등록한 반증선(DESIGN-VALIDATION.md 3절)과 비교. 표본이 모자라면 '표본 부족'."""
    out = {}
    folded = m["원칙2 ro가 접은 항목"]
    out["원칙2 확신 기준"] = ("표본 부족" if folded < 50 else
                          "반증" if m["원칙2 접힌 항목 되돌림 비율"] >= 0.10 else "통과")
    edits = m["원칙2 수정 전체"]
    out["원칙2 너무 많이 묻기"] = ("표본 부족" if edits < 20 else
                            "반증" if m["원칙2 다르게 고른 비율"] < 0.05 else "통과")
    out["원칙4 불림"] = "반증 후보(다운로드 증가 여부 확인)" if m["원칙4 ro를 부른 날"] < 4 else "통과"
    return out


def main(argv=None):
    p = argparse.ArgumentParser(description="디자인 철학 v2 관찰 지표(개수만)")
    p.add_argument("--days", type=int, default=30)
    p.add_argument("--downloads", default="~/Downloads", help="파일 수만 센다")
    a = p.parse_args(argv)
    m = compute(days=a.days, downloads=a.downloads)
    for k, v in {**m, **{f"판정 · {k}": v for k, v in verdicts(m).items()}}.items():
        print(f"{k}: {v}")
    counts = nudges(days=a.days)
    for t, c in sorted(counts.items()):
        print(f"원칙4 트리거 {t}: " + ", ".join(f"{k} {v}" for k, v in c.items()))
    for k, v in nudge_verdicts(counts).items():
        print(f"판정 · 원칙4 {k}: {v}")


if __name__ == "__main__":
    main()
