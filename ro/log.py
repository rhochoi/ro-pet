"""Log 단계: append-only JSONL 이벤트 기록 + 일일 요약.

비밀값은 저장 전에 마스킹한다(키 이름·값 패턴 기준).
"""
import datetime
import json
import os
import re
import secrets
import time
from collections import Counter
from pathlib import Path

from . import fsutil

LOG_DIR = "~/.ro/log"
_DAY_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")
_CTRL_RE = re.compile(r"[\r\n\x00-\x1f\x7f]+")


def _valid_day(value):
    s = str(value).strip()
    if not _DAY_RE.match(s):
        raise ValueError(f"날짜는 YYYY-MM-DD 형식이어야 합니다: {value}")
    try:
        datetime.date.fromisoformat(s)
    except ValueError:
        raise ValueError(f"올바른 날짜가 아닙니다: {value}") from None
    return s


def _single_line(text):
    return _CTRL_RE.sub(" ", str(text)).strip()
SECRET_KEY = re.compile(r"pass(word)?|secret|token|api[_-]?key|credential|private[_-]?key", re.I)
SECRET_VALUE = re.compile(
    r"(sk-[A-Za-z0-9_-]{16,}|gh[pousr]_[A-Za-z0-9]{20,}|github_pat_[A-Za-z0-9_]{20,}|AKIA[0-9A-Z]{16}"
    r"|AIza[0-9A-Za-z_-]{30,}|xox[abp]-[A-Za-z0-9-]{10,}|[sr]k_(?:live|test)_[A-Za-z0-9]{10,}"
    r"|-----BEGIN [A-Z ]*PRIVATE KEY-----"
    r"|\beyJ[A-Za-z0-9_-]{8,}\.eyJ[A-Za-z0-9_-]{4,}\.[A-Za-z0-9_-]+)"  # JWT
)
MASK = "[REDACTED]"
# 자유 문장 속 비밀: "password=..." "token: ..." "Bearer ..." (키 이름은 남기고 값만 가린다)
# 값이 따옴표로 묶이면 따옴표 안 전체(공백 포함)를 가린다. 환경변수 이름(DB_PASSWORD·OPENAI_API_KEY·
# AWS_SECRET_ACCESS_KEY·PGPASSWORD)도 잡되, token_count·tokens처럼 뒤에 다른 말이 붙은 이름은 그대로 둔다.
SECRET_ASSIGN = re.compile(
    r"(?<![A-Za-z0-9_-])((?:[A-Za-z0-9]+[_-])*(?:PG)?(?:pass(?:word|wd)?|secret|token|api[_-]?key|authorization)"
    r"(?:[_-]?(?:access[_-]?)?key)?)(\s*[:=]\s*)(?!\[REDACTED\])"
    r"(\"[^\"]*\"|'[^']*'|[^\s&]+)", re.I)   # 따옴표 없는 값은 & 앞까지(URL의 다음 매개변수는 남긴다)
# "비밀번호는 hunter2"처럼 조사로 이어진 값: 숫자·기호가 섞인 낱말만 비밀로 본다("비밀번호는 어떻게"는 그대로)
SECRET_KO = re.compile(
    r"(비밀\s*번호|패스워드|암호|토큰)(\s*[:=]\s*|\s*(?:은|는|이|가)\s+(?=\"|'|\S*[0-9!@#$%^&*_-]))"
    r"(?!\[REDACTED\])(\"[^\"]*\"|'[^']*'|\S+)")
BEARER = re.compile(r"\bBearer\s+(?!\[REDACTED\])[A-Za-z0-9._~+/-]+=*", re.I)
# 여러 줄 키 블록은 머리만이 아니라 본문까지 통째로 가린다(END가 잘려 없으면 끝까지)
PEM_BLOCK = re.compile(r"-----BEGIN [A-Z0-9 ]*(?:PRIVATE KEY|CERTIFICATE|PGP PRIVATE KEY BLOCK)-----"
                       r"[\s\S]*?(?:-----END [A-Z0-9 ]*-----|\Z)")
# https://user:pass@host 의 아이디·비밀번호
URL_USERINFO = re.compile(r"\b([a-z][a-z0-9+.-]*://)[^/\s@]+@", re.I)


def redact(obj):
    if isinstance(obj, dict):
        return {k: MASK if SECRET_KEY.search(str(k)) else redact(v) for k, v in obj.items()}
    if isinstance(obj, list):
        return [redact(v) for v in obj]
    if isinstance(obj, str):
        obj = PEM_BLOCK.sub(MASK, obj)
        obj = URL_USERINFO.sub(lambda m: m[1] + MASK + "@", obj)
        obj = SECRET_VALUE.sub(MASK, obj)
        obj = BEARER.sub("Bearer " + MASK, obj)
        obj = SECRET_ASSIGN.sub(lambda m: m[1] + m[2] + MASK, obj)
        return SECRET_KO.sub(lambda m: m[1] + m[2] + MASK, obj)
    return obj


def _resolve_dir(log_dir):
    ro_home = os.environ.get("RO_HOME")
    if log_dir == LOG_DIR and ro_home:
        cand = Path(ro_home).expanduser()
        try:
            if cand.resolve().is_relative_to(Path.home().resolve()):
                return cand / "log"
        except OSError:
            pass
    return Path(log_dir).expanduser()


def _file(day, log_dir):
    return _resolve_dir(log_dir) / f"{day}.jsonl"


def append(kind, summary, data=None, engine=None, log_dir=LOG_DIR, at=None):
    """이벤트 한 줄 추가. at(epoch 초)을 주면 그 시각의 이벤트로 기록한다(수집기용). 반환: 기록된 이벤트."""
    kind = _single_line(kind)
    summary = _single_line(summary)
    if not kind or not summary:
        raise ValueError("종류(kind)와 요약(summary)은 비워 둘 수 없습니다.")
    now = at if at is not None else time.time()
    event = redact({
        "ts": time.strftime("%Y-%m-%dT%H:%M:%S%z", time.localtime(now)),
        "id": secrets.token_hex(6),  # 같은 초·같은 요약의 다른 기록도 따로 가리킬 수 있게
        "kind": kind, "engine": engine, "summary": summary, "data": data or {},
    })
    path = _file(time.strftime("%Y-%m-%d", time.localtime(now)), log_dir)
    fsutil.ensure_dir(path.parent)
    fd = os.open(path, os.O_WRONLY | os.O_APPEND | os.O_CREAT, 0o600)
    with os.fdopen(fd, "a", encoding="utf-8") as f:
        f.write(json.dumps(event, ensure_ascii=False) + "\n")
    return event


def read(day, log_dir=LOG_DIR):
    path = _file(day, log_dir)
    if not path.exists():
        return []
    events = []
    for line in path.read_text(encoding="utf-8").splitlines():
        try:
            events.append(json.loads(line))
        except json.JSONDecodeError:
            continue  # 손상된 줄은 건너뛴다(기록은 수정하지 않음)
    return events


def summarize(day, log_dir=LOG_DIR):
    day = _valid_day(day)
    events = read(day, log_dir)
    if not events:
        return f"{day}: 기록 없음"
    kinds = Counter(e["kind"] for e in events)
    engines = Counter(e["engine"] for e in events if e.get("engine"))
    lines = [f"# {day} — 이벤트 {len(events)}개",
             "종류: " + ", ".join(f"{k} {n}" for k, n in kinds.most_common())]
    if engines:
        lines.append("엔진: " + ", ".join(f"{k} {n}" for k, n in engines.most_common()))
    lines.append("")
    lines += [f"- {e['ts'][11:19]} [{e['kind']}] {e['summary']}" for e in events[-10:]]
    if len(events) > 10:
        lines.append(f"(앞의 {len(events) - 10}개는 생략 — 전체: ro log tail -n {len(events)})")
    return "\n".join(lines)


def read_all(log_dir=LOG_DIR):
    events = []
    for path in sorted(_resolve_dir(log_dir).glob("*.jsonl")):
        events += read(path.stem, log_dir)
    return events


def delete(before=None, log_dir=LOG_DIR, home=None):
    """기록 삭제(사용자 요청 전용). before(YYYY-MM-DD)를 주면 그 날짜 이전만, 없으면 전부. 삭제한 파일 수 반환.
    기록에서 만들어진 것도 함께 지운다: 같은 날짜의 일간 통계, 기록에서 나온 학습 후보(승인 대기),
    전부 지울 때는 직전 질문·답변(ask -c)."""
    if before is not None:
        before = _valid_day(before)
    resolved = _resolve_dir(log_dir)
    n = 0
    for path in resolved.glob("*.jsonl"):
        if before is None or (_DAY_RE.match(path.stem) and path.stem < before):
            path.unlink()
            n += 1
    if home:
        h = Path(home).expanduser()
    elif resolved.name == "log":  # ~/.ro/log → ~/.ro. 다른 폴더를 넘기면 위쪽을 건드리지 않는다
        h = resolved.parent
    else:
        return n
    for path in (h / "stats").glob("*.json"):
        if before is None or (_DAY_RE.match(path.stem) and path.stem < before):
            path.unlink(missing_ok=True)
    pending = h / "pending.json"
    if pending.exists():  # 남은 기록으로 다음 propose/distill 때 다시 계산된다
        pending.unlink()
    if before is None:
        (h / "last_ask.json").unlink(missing_ok=True)
    return n
