"""활동 기록 시험판: 이 Mac에서 '어디서 무엇을 했나'를 켠 동안만 로컬에 남긴다(docs/ACTIVITY-HISTORY-DESIGN.md).

남기는 것: 앞에 있는 앱과 머문 시간, 웹 AI 사이트의 탭 제목(가린 뒤). 최근 고친 문서는 넘길 때 Spotlight로 본다.
남기지 않는 것: 키 입력·스크린샷·녹음·클립보드·창 제목·웹 AI가 아닌 사이트 주소·시크릿 창.
제외 앱(비밀번호 관리자·메신저·메일·건강)이 앞에 있는 동안은 아무것도 남기지 않는다.
대화 '내용'은 넘기지 않는다 — 위치만 넘기고, 내용은 옛 AI의 인수인계 글이나 내보내기 파일로 채운다.
"""
import json
import os
import re
import subprocess
import threading
import time
from pathlib import Path
from urllib.parse import urlsplit

from . import config, engines, findeval, fsutil, log

DIR = "~/.ro/activity"
KEEP_DAYS = 7
INTERVAL = 15          # 초. 앞 앱이 바뀌었는지 보는 간격
IDLE_AFTER = 300       # 초. 입력이 이만큼 없으면 자리 비움으로 본다
AI_SITES = {
    "chatgpt.com": "ChatGPT", "chat.openai.com": "ChatGPT", "claude.ai": "Claude",
    "gemini.google.com": "Gemini", "aistudio.google.com": "Google AI Studio",
    "notebooklm.google.com": "NotebookLM", "perplexity.ai": "Perplexity",
    "copilot.microsoft.com": "Copilot", "grok.com": "Grok", "chat.deepseek.com": "DeepSeek",
    "chat.mistral.ai": "Mistral",
}
# 앞에 있는 동안 아무것도 남기지 않는 앱(이름 일부, 대소문자 무시): 비밀번호·대화 상대·건강 정보
EXCLUDED = ("1password", "bitwarden", "keychain access", "passwords", "dashlane", "lastpass",
            "messages", "kakaotalk", "slack", "discord", "telegram", "whatsapp", "line", "signal",
            "mail", "outlook", "spark", "microsoft teams", "health")
LOCKED = {"loginwindow", "ScreenSaverEngine"}
CHROMIUM = {"Google Chrome", "Arc", "Microsoft Edge", "Brave Browser", "Chromium", "Vivaldi"}
SAFARI = {"Safari"}


def _x(p):
    return engines._x(p)


def _cfg():
    v = config.load(str(_x("~/.ro"))).get("activity")
    return v if isinstance(v, dict) else {}


def _set(**changes):
    return config.update(str(_x("~/.ro")), activity={**_cfg(), **changes})["activity"]


def enabled(now=None):
    c, now = _cfg(), time.time() if now is None else now
    return bool(c.get("on")) and float(c.get("paused_until") or 0) <= now


def turn_on():
    return _set(on=True, paused_until=0, since=_cfg().get("since") or time.time())


def turn_off():
    return _set(on=False, paused_until=0)


def pause(minutes, now=None):
    return _set(paused_until=(time.time() if now is None else now) + max(1, int(minutes)) * 60)


# ---- 한 번 보기 ---------------------------------------------------------------

def _run(args, runner, timeout=3):
    try:
        r = runner(args, capture_output=True, text=True, timeout=timeout)
    except (OSError, subprocess.TimeoutExpired):
        return None, "error"
    return (r.stdout, "ok") if r.returncode == 0 else (None, (r.stderr or "").strip())


def _app_name(bundle):
    return Path(bundle).name[:-4] if bundle and bundle.endswith(".app") else None


def excluded(app):
    """이름이 제외 목록 낱말을 포함하면 제외('Microsoft Outlook'·'1Password 8'). 'Gmail' 같은 부분 일치는 아니다."""
    a = (app or "").lower()
    words = set(re.split(r"[\s\-_.]+", a))
    return any((x in a) if " " in x else (x in words) for x in EXCLUDED)


def idle_seconds(runner=subprocess.run):
    out, _ = _run(["ioreg", "-c", "IOHIDSystem", "-d", "4"], runner)
    m = re.search(r'"HIDIdleTime"\s*=\s*(\d+)', out or "")
    return int(m[1]) / 1e9 if m else 0.0


def browser_tab(app, runner=subprocess.run):
    """(사이트 이름, 제목) 또는 None. 웹 AI 사이트가 아니거나 시크릿 창이면 None. 권한이 없으면 'denied'."""
    if app in CHROMIUM:
        script = (f'tell application "{app}" to if (count of windows) > 0 then '
                  'set m to "normal"\ntry\nset m to mode of front window\nend try\n'
                  'return m & linefeed & (URL of active tab of front window) & linefeed & (title of active tab of front window)\n'
                  'end if')
    elif app in SAFARI:
        script = ('tell application "Safari" to if (count of windows) > 0 then '
                  'return "normal" & linefeed & (URL of current tab of front window) & linefeed & (name of current tab of front window)')
    else:
        return None
    out, err = _run(["osascript", "-e", script], runner)
    if out is None:
        return "denied" if "-1743" in (err or "") or "not allowed" in (err or "").lower() else None
    parts = out.rstrip("\n").split("\n", 2)
    if len(parts) < 3 or parts[0].strip() == "incognito":
        return None
    host = (urlsplit(parts[1].strip()).hostname or "").lower()
    site = next((name for h, name in AI_SITES.items() if host == h or host.endswith("." + h)), None)
    return (site, parts[2].strip()) if site else None


# ro pro: 펫 호스트(pet_mac.swift)가 앞 앱·유휴 시간을 밀어 준다. 신선하면 ioreg·lsappinfo를 띄우지 않는다.
SENSOR = {}
SENSOR_FRESH = INTERVAL * 2


def push(ev):
    """센서 한 줄을 받아 둔다. 제외 앱 이름은 담지 않는다."""
    t = ev.get("t", time.time())
    if ev.get("type") == "front":
        app = ev.get("app") or ""
        SENSOR["app"] = (None if excluded(app) or ev.get("private") else app, t)
    elif ev.get("type") == "idle":
        SENSOR["idle"] = (float(ev.get("seconds", 0)), t)


def _sensed(key, now):
    v = SENSOR.get(key)
    return v if v and 0 <= now - v[1] <= SENSOR_FRESH else None


def observe(runner=subprocess.run, now=None):
    """지금 이 순간의 관측. 남길 것이 없으면 None(제외 앱·앞 앱 모름)."""
    from . import handoff
    now = time.time() if now is None else now
    idle = _sensed("idle", now)
    if (idle[0] + now - idle[1] if idle else idle_seconds(runner)) >= IDLE_AFTER:
        return {"t": now, "idle": True}
    front = _sensed("app", now)
    if front and front[0] is None:
        return None                      # 센서가 이미 제외 앱이라고 알렸다
    app = front[0] if front else _app_name(handoff.front_app(runner))
    if app in LOCKED:                    # 잠금 화면·화면 보호기: 자리 비움
        return {"t": now, "idle": True}
    if not app or excluded(app):
        return None
    ev = {"t": now, "app": app}
    tab = browser_tab(app, runner)
    if tab == "denied":
        ev["browser"] = "denied"
    elif tab:
        ev["site"], ev["title"] = tab[0], handoff._mask(tab[1])[:120]
    return ev


# ---- 남기기 -----------------------------------------------------------------

def _day_file(t):
    return _x(DIR) / (time.strftime("%Y-%m-%d", time.localtime(t)) + ".jsonl")


def _status_file():
    return _x(DIR) / "status.json"


def status():
    try:
        s = json.loads(_status_file().read_text(encoding="utf-8"))
        return s if isinstance(s, dict) else {}
    except (OSError, ValueError):
        return {}


def _append(ev):
    f = _day_file(ev["t"])
    fsutil.ensure_dir(f.parent)
    fd = os.open(f, os.O_WRONLY | os.O_APPEND | os.O_CREAT, 0o600)
    with os.fdopen(fd, "a", encoding="utf-8") as fh:
        fh.write(json.dumps(ev, ensure_ascii=False) + "\n")


def _key(ev):
    return None if ev is None else ("idle",) if ev.get("idle") else (ev.get("app"), ev.get("site"), ev.get("title"))


def prune(now=None):
    """KEEP_DAYS가 지난 날짜 파일만 지운다(ro가 만든 YYYY-MM-DD.jsonl만)."""
    now = time.time() if now is None else now
    d = _x(DIR)
    for f in d.glob("*.jsonl") if d.is_dir() else []:
        if re.fullmatch(r"\d{4}-\d{2}-\d{2}\.jsonl", f.name) and now - f.stat().st_mtime > KEEP_DAYS * 86400:
            f.unlink(missing_ok=True)


def tick(runner=subprocess.run, now=None):
    """한 번 보고, 바뀌었을 때만 남긴다. 펫의 기록 스레드가 INTERVAL마다 부른다."""
    now = time.time() if now is None else now
    if not enabled(now):
        return None
    st = status()
    last_tick = float(st.get("tick") or 0)
    ev = observe(runner, now)
    if last_tick and now - last_tick > INTERVAL * 4:   # 잠자기·멈춤 뒤: 그 사이를 머문 시간으로 치지 않는다
        _append({"t": last_tick + INTERVAL, "gap": True})
        st["last"] = None
    key = _key(ev)
    if key != (tuple(st["last"]) if st.get("last") else None):
        _append(ev if ev is not None else {"t": now, "gap": True})
        st["last"] = list(key) if key else None
    st.update(tick=now, browser=(ev or {}).get("browser") or ("ok" if (ev or {}).get("site") else st.get("browser")))
    fsutil.atomic_write(_status_file(), json.dumps(st, ensure_ascii=False))
    if int(now) % 3600 < INTERVAL:
        prune(now)
    return ev


# ---- 읽기 -------------------------------------------------------------------

def events(since, now=None):
    now = time.time() if now is None else now
    out, t = [], since - 86400
    while t <= now + 86400:
        f = _day_file(t)
        t += 86400
        try:
            lines = f.read_text(encoding="utf-8").splitlines()
        except OSError:
            continue
        for line in lines:
            try:
                ev = json.loads(line)
            except ValueError:
                continue
            if isinstance(ev, dict) and since <= float(ev.get("t", 0)) <= now:
                out.append(ev)
    return sorted(out, key=lambda e: e["t"])


def spans(since, now=None):
    """(시작, 끝, 관측) 목록. 끝은 다음 관측 시각, 마지막은 마지막 기록 시각(멈췄으면 거기까지)."""
    now = time.time() if now is None else now
    evs = events(since, now)
    end_last = min(now, float(status().get("tick") or now) + INTERVAL)
    out = []
    for i, ev in enumerate(evs):
        end = evs[i + 1]["t"] if i + 1 < len(evs) else end_last
        if not ev.get("gap") and not ev.get("idle") and end > ev["t"]:
            out.append((ev["t"], end, ev))
    return out


def last_web_ai(hours=24, now=None):
    now = time.time() if now is None else now
    ts = [e for s, e, ev in spans(now - hours * 3600, now) if ev.get("site")]
    return max(ts) if ts else None


def summary(hours=6, now=None):
    now = time.time() if now is None else now
    apps, web = {}, {}
    for s, e, ev in spans(now - hours * 3600, now):
        apps[ev["app"]] = apps.get(ev["app"], 0) + (e - s)
        if ev.get("site"):
            k = (ev["site"], ev.get("title") or "")
            first, last, total = web.get(k, (s, e, 0))
            web[k] = (min(first, s), max(last, e), total + (e - s))
    return {"apps": sorted(apps.items(), key=lambda x: -x[1]),
            "web": sorted(((k[0], k[1], *v) for k, v in web.items()), key=lambda x: -x[3])}


def recent_docs(hours=6, limit=8, runner=subprocess.run, roots=None):
    """파일 찾기 폴더에서 최근 수정한 문서(Spotlight). 숨김·비밀·빌드 폴더는 뺀다. 내용은 읽지 않는다."""
    roots = roots or findeval.default_roots(str(_x("~/.ro")))
    q = f"kMDItemFSContentChangeDate >= $time.now(-{int(hours * 3600)}) && kMDItemContentType != public.folder"
    found = []
    for root in roots:
        r = _x(root)
        out, _ = _run(["mdfind", "-onlyin", str(r), q], runner, timeout=5)
        for line in (out or "").splitlines():
            p = Path(line)
            try:
                rel = p.relative_to(r)
            except ValueError:
                continue
            if any(findeval._blocked(part) for part in rel.parts) or not p.is_file():
                continue
            found.append((p.stat().st_mtime, p))
    found.sort(reverse=True)
    return [(t, p) for t, p in found[:limit]]


def _hm(t):
    return time.strftime("%H:%M", time.localtime(t))


def _mins(sec):
    return f"{max(1, round(sec / 60))}분"


def section(hours=6, now=None, runner=subprocess.run):
    """인수인계 문서에 넣을 '최근 활동' 절. 켜져 있지 않거나 남은 게 없으면 []."""
    if not _cfg().get("on"):
        return []
    from . import handoff
    now = time.time() if now is None else now
    s = summary(hours, now)
    docs = recent_docs(hours, runner=runner)
    if not (s["apps"] or s["web"] or docs):
        return []
    out = [f"## 최근 활동(이 Mac, 최근 {hours}시간)", "",
           "어디서 무엇을 했는지만 담았습니다. 웹 AI 대화의 내용은 이 Mac에 없어 넘기지 못합니다."]
    if s["web"]:
        out += ["", "웹 AI 대화(사이트 · 탭 제목):"]
        out += [f"- {site} · {title or '(제목 없음)'} ({_hm(a)}–{_hm(b)}, {_mins(total)})"
                for site, title, a, b, total in s["web"][:8]]
    if s["apps"]:
        out += ["", "많이 쓴 앱: " + ", ".join(f"{a} {_mins(t)}" for a, t in s["apps"][:6])]
    if docs:
        out += ["", "최근 고친 문서:"] + [f"- `{handoff._mask(str(p))}` ({_hm(t)})" for t, p in docs]
    stalled = enabled(now) and now - float(status().get("tick") or 0) > INTERVAL * 8
    if stalled:
        out += ["", "참고: 활동 기록이 한동안 멈춰 있었습니다. 최근 일이 빠졌을 수 있습니다."]
    return out + [""]


# ---- 펫이 돌리는 기록 스레드 ---------------------------------------------------

class Recorder(threading.Thread):
    def __init__(self, interval=INTERVAL):
        super().__init__(daemon=True, name="ro-activity")
        self.interval, self.stop = interval, threading.Event()

    def run(self):
        while not self.stop.wait(self.interval):
            try:
                tick()
            except Exception as e:   # 기록이 펫을 멈추게 하지 않는다. 대신 상태에 남겨 조용히 멈추지 않게 한다
                try:
                    fsutil.atomic_write(_status_file(), json.dumps({**status(), "error": type(e).__name__}))
                except OSError:
                    pass


# ---- 상태·CLI ----------------------------------------------------------------

def _metrics_file():
    return _x(DIR) / "metrics.json"


def _log_handoff_counts():
    handoffs = with_act = rated_ok = rated_miss = 0
    for ev in _log_events():
        if ev.get("kind") == "handoff":
            handoffs += 1
            if (ev.get("data") or {}).get("activity"):
                with_act += 1
        elif ev.get("kind") == "handoff_rate":
            ok = (ev.get("data") or {}).get("ok")
            rated_ok, rated_miss = rated_ok + bool(ok), rated_miss + (not ok)
    return {"handoffs": handoffs, "handoffs_with_activity": with_act,
            "rated_ok": rated_ok, "rated_miss": rated_miss}


def _load_metrics():
    f = _metrics_file()
    if f.is_file():
        try:
            d = json.loads(f.read_text(encoding="utf-8"))
            if isinstance(d, dict):
                return {k: int(d.get(k) or 0) for k in ("handoffs", "handoffs_with_activity", "rated_ok", "rated_miss")}
        except (OSError, ValueError, TypeError):
            pass
    return _log_handoff_counts()


def _save_metrics(data):
    f = _metrics_file()
    fsutil.ensure_dir(f.parent)
    fsutil.atomic_write(f, json.dumps(data))


def record_handoff(with_activity=False):
    m = _load_metrics()
    m["handoffs"] += 1
    if with_activity:
        m["handoffs_with_activity"] += 1
    _save_metrics(m)
    return m


def record_rating(ok):
    m = _load_metrics()
    if ok:
        m["rated_ok"] += 1
    else:
        m["rated_miss"] += 1
    _save_metrics(m)
    return m


def has_handoff():
    return _load_metrics()["handoffs"] > 0


def report(now=None):
    """켠 뒤 성공·폐기 기준을 보는 숫자(개수만)."""
    now = time.time() if now is None else now
    c, st, m = _cfg(), status(), _load_metrics()
    since = float(c.get("since") or now)
    tick_at = float(st.get("tick") or 0)
    return {"on": bool(c.get("on")), "paused_until": float(c.get("paused_until") or 0), "since": since,
            "days": int((now - since) // 86400), "last_tick": tick_at or None,
            "stalled": enabled(now) and (not tick_at or now - tick_at > INTERVAL * 8),
            "browser": st.get("browser"), "error": st.get("error"),
            "handoffs_with_activity": m["handoffs_with_activity"],
            "rated_ok": m["rated_ok"], "rated_miss": m["rated_miss"]}


def _log_events():
    d = _x(log.LOG_DIR)
    for f in sorted(d.glob("*.jsonl")) if d.is_dir() else []:
        for line in f.read_text(encoding="utf-8", errors="replace").splitlines():
            try:
                ev = json.loads(line)
            except ValueError:
                continue
            if isinstance(ev, dict):
                yield ev


def clear():
    d = _x(DIR)
    n = 0
    for f in (list(d.glob("*.jsonl")) + [d / "status.json", d / "metrics.json"]) if d.is_dir() else []:
        if f.exists():
            f.unlink()
            n += 1
    return n


def cli(action="status", minutes=60, yes=False):
    if action == "on":
        turn_on()
        print("활동 기록을 켰어요. 펫이 떠 있는 동안 앞 앱과 웹 AI 탭 제목만 남깁니다(키 입력·화면은 남기지 않음).")
        print("브라우저 탭 제목은 처음 한 번 macOS가 '자동화' 허용을 물어요. 끄기: ro activity off")
        return 0
    if action == "off":
        turn_off()
        print("활동 기록을 껐어요. 남은 기록은 7일 뒤 지워지고, 지금 지우려면: ro activity clear --yes")
        return 0
    if action == "pause":
        pause(minutes)
        print(f"{minutes}분 동안 멈춰요.")
        return 0
    if action == "clear":
        if not yes:
            print("활동 기록을 모두 지웁니다(되돌릴 수 없음). 진행하려면: ro activity clear --yes")
            return 0
        print(f"지웠어요 · 파일 {clear()}개")
        return 0
    if action == "today":
        now = time.time()
        midnight = time.mktime(time.localtime(now)[:3] + (0, 0, 0, 0, 0, -1))
        lines = section(hours=max(1, round((now - midnight) / 3600)), now=now)
        print("\n".join(lines) if lines else "오늘 남은 활동 기록이 없어요(켜져 있는지: ro activity status).")
        return 0
    r = report()
    state = "켜짐" if r["on"] else "꺼짐"
    if r["on"] and r["paused_until"] > time.time():
        state += f" · {time.strftime('%H:%M', time.localtime(r['paused_until']))}까지 멈춤"
    print(f"활동 기록: {state}")
    if r["on"]:
        print(f"  마지막 기록: {time.strftime('%m-%d %H:%M', time.localtime(r['last_tick'])) if r['last_tick'] else '없음(펫이 떠 있어야 기록돼요)'}"
              + (" — 멈춰 있어요" if r["stalled"] else ""))
        if r["browser"] == "denied":
            print("  브라우저 탭을 읽지 못해요: 시스템 설정 > 개인정보 보호 및 보안 > 자동화에서 허용하세요.")
        if r["error"]:
            print(f"  기록 오류: {r['error']}")
        print(f"  시험 {r['days']}일째 / 14일 · 최근 활동이 들어간 인수인계 {r['handoffs_with_activity']}번(3번 미만이면 접음)"
              f" · 평가 ok {r['rated_ok']} / miss {r['rated_miss']}(ok가 절반 미만이면 접음)")
    return 0
