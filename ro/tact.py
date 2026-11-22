"""TactGate: ro pro가 먼저 다가가도 되는 순간인지 정한다. 순수 판단만 하고 화면·파일은 건드리지 않는다.

디자인 원칙 4(2026-11-16 개정)를 코드로 옮긴 것이다.
- 동의(config pro_nudges=true) 전에는 무엇도 내지 않는다. mini에서는 이 모듈을 쓰지 않는다.
- 비밀 앱(1Password·키체인·시크릿 창)이 앞에 있으면 그 관측은 큐에 넣기 전에 버린다.
- 2단계(토스트)를 1단계(표정)로 낮추는 순간: 전체 화면·카메라/마이크 사용 중·입력 중(HID 유휴 < 2.5초).
- '찾기 헤맴'은 사용자가 직접 정리하는 중(대상 폴더에 20초 안 파일 I/O)이거나 Spotlight로 앱을 띄운 것(10초 안
  앱 실행)이면 없던 일로 한다.
- 압축 해제·AirDrop·웹 페이지 저장(HTML+_files)처럼 한꺼번에 들어오는 파일은 12초 조용해질 때까지 묶는다.
- 2단계는 하루 상한(기본 1회), 끄거나 무시하면 1일 → 3일 → 7일 물러나고, designmetrics가 강등한 트리거는 1단계만.
"""
import time
from collections import defaultdict, deque
from pathlib import Path

from . import activity, config, designmetrics, log

DROP, QUIET, LEVEL1, LEVEL2 = "drop", "quiet", "level1", "level2"
TYPING_IDLE = 2.5          # 초. HID 유휴가 이보다 짧으면 입력 중
IDLE_REPORT_EVERY = 5      # 초. 호스트가 유휴 시간을 읽는 주기(pet_mac.swift IdleTracker.every)
SELF_ORGANIZING = 20       # 초. 대상 폴더에 이만큼 안에 사용자 I/O가 있으면 직접 정리 중
LAUNCHER = 10              # 초. 이만큼 안에 앱이 새로 떴으면 Spotlight를 앱 런처로 쓴 것
BURST_QUIET = 12           # 초. 같은 폴더 유입이 이만큼 조용하면 한 묶음으로 낸다
DAILY_CAP = 1
BACKOFF_DAYS = (1, 3, 7)
SEEKING = {"find_lost"}    # 사용자 직접 정리·앱 런처와 헷갈리는 트리거
PRIVATE_HINTS = ("private", "incognito", "시크릿", "비공개")


class TactGate:
    def __init__(self, home=config.HOME, log_dir=log.LOG_DIR, clock=time.time, daily_cap=DAILY_CAP):
        self.home, self.log_dir, self.clock, self.daily_cap = home, log_dir, clock, daily_cap
        self.front = None            # {"app", "fullscreen", "t"} — 비밀 앱은 담지 않는다
        self.capture = False         # 카메라·마이크 사용 중
        self.hid_idle = None         # (초, 받은 시각)
        self.user_io = deque(maxlen=256)     # (폴더, 시각)
        self.launches = deque(maxlen=32)     # 시각
        self.arrivals = defaultdict(list)    # 폴더 → [(경로, 시각)]

    # ---- 센서 입력 ----
    def on_sensor(self, ev):
        """pet_mac.swift가 보낸 한 줄(dict). 비밀 앱 관측은 여기서 버린다. 반환: 받아들였는지."""
        now = ev.get("t", self.clock())
        kind = ev.get("type")
        if kind == "front":
            app, title = ev.get("app") or "", (ev.get("window") or "").casefold()
            if activity.excluded(app) or ev.get("private") or any(h in title for h in PRIVATE_HINTS):
                self.front = {"app": None, "private": True, "fullscreen": False, "t": now}
                return False
            self.front = {"app": app, "private": False, "fullscreen": bool(ev.get("fullscreen")), "t": now}
            if ev.get("launched"):
                self.launches.append(now)
        elif kind == "idle":
            self.hid_idle = (float(ev.get("seconds", 0)), now)
        elif kind == "capture":
            self.capture = bool(ev.get("active"))
        elif kind == "fullscreen" and self.front:
            self.front["fullscreen"] = bool(ev.get("active"))
        elif kind == "user_io":
            self.user_io.append((str(Path(ev["path"]).parent), now))
        else:
            return False
        return True

    def on_arrival(self, path, now=None):
        """새 파일이 생김(다운로드·압축 해제·AirDrop). 묶음은 flush()가 낸다."""
        now = self.clock() if now is None else now
        p = Path(path)
        folder = str(p.parent.parent if p.parent.name.endswith("_files") else p.parent)  # HTML 저장 묶음
        self.arrivals[folder].append((str(p), now))

    def flush(self, now=None):
        """조용해진 폴더의 유입 묶음. 반환: [{"folder", "paths", "first", "last"}]."""
        now = self.clock() if now is None else now
        out = []
        for folder, items in list(self.arrivals.items()):
            if now - items[-1][1] >= BURST_QUIET:
                out.append({"folder": folder, "paths": [p for p, _ in items], "first": items[0][1],
                             "last": items[-1][1]})
                del self.arrivals[folder]
        return out

    # ---- 판단 ----
    def consented(self):
        return config.load(self.home).get("pro_nudges") is True

    def _busy(self, now):
        if self.front and self.front.get("fullscreen"):
            return "전체 화면"
        if self.capture:
            return "카메라·마이크 사용 중"
        if self.hid_idle:
            seconds, at = self.hid_idle
            # 호스트는 5초마다 읽고 입력 중이면 매번 보낸다. 마지막 보고가 입력 중이고 한 주기 안이면 아직 입력 중으로 본다
            if seconds + (now - at) < TYPING_IDLE or (seconds < TYPING_IDLE and now - at < IDLE_REPORT_EVERY + 1):
                return "입력 중"
        return None

    def _history(self, trigger, now):
        """(오늘 2단계 노출 수, 이 트리거 다음 허용 시각)."""
        events = designmetrics._events(self.log_dir, now - 30 * 86400)
        mine = [e for e in events if e["kind"] == designmetrics.NUDGE]
        day = time.strftime("%Y-%m-%d", time.localtime(now))
        shown_today = sum(1 for e in mine if e["data"].get("action") == "shown" and e["data"].get("level", 2) == 2
                          and time.strftime("%Y-%m-%d", time.localtime(e["t"])) == day)
        streak, last_shown = 0, None
        for e in mine:
            if e["data"].get("trigger") != trigger or e["data"].get("level", 2) != 2:
                continue
            a = e["data"].get("action")
            if a == "shown":
                last_shown = e["t"]
            elif a in ("off", "ignored"):
                streak += 1
            elif a == "accepted":
                streak = 0
        if not streak or last_shown is None:
            return shown_today, 0.0
        return shown_today, last_shown + BACKOFF_DAYS[min(streak, len(BACKOFF_DAYS)) - 1] * 86400

    def decide(self, trigger, folder=None, now=None):
        """(결정, 이유). 결정: drop(없던 일) · quiet(아무것도 안 함) · level1(표정) · level2(토스트)."""
        now = self.clock() if now is None else now
        cfg = config.load(self.home)
        if cfg.get("pro_nudges") is not True:
            return QUIET, "동의 전"
        if trigger in (cfg.get("nudges_off") or []):
            return QUIET, "꺼 둔 유형"
        if self.front and self.front.get("private"):
            return DROP, "비밀 앱"
        if trigger in SEEKING:
            if folder and any(f == str(folder) and now - t < SELF_ORGANIZING for f, t in self.user_io):
                return DROP, "직접 정리 중"
            if any(now - t < LAUNCHER for t in self.launches):
                return DROP, "앱 실행(런처)"
        busy = self._busy(now)
        if busy:
            return LEVEL1, busy
        if designmetrics.kill_switch(self.log_dir, now=now):
            return LEVEL1, "원칙4 킬스위치"
        if designmetrics.demoted(trigger, self.log_dir, now=now):
            return LEVEL1, "강등된 트리거"
        shown_today, next_ok = self._history(trigger, now)
        if now < next_ok:
            return LEVEL1, "물러나는 중"
        if shown_today >= self.daily_cap:
            return LEVEL1, "오늘 상한"
        return LEVEL2, "조건 충족"

    def record(self, trigger, action, level=2, batch=None, now=None, why=None):
        """노출·수락·끄기·무시를 개수용으로 남긴다(designmetrics). 이름·내용은 남기지 않는다."""
        return designmetrics.record_nudge(trigger, action, batch=batch, log_dir=self.log_dir,
                                          at=self.clock() if now is None else now, level=level, why=why)
