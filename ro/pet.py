"""Pet 단계: 'RO — LOG BOT v1 (층 셋, 눈 둘. 그 이상은 더하지 않는다.)' 데스크톱 비서 UI 및 브리지.

CONSTRUCTION (정밀 그리드 규격 — 1u 기준):
- 층 셋 높이: 머리 8u, 몸 6u, 바닥 6u, 층 사이 간격 1u, 양끝은 완전히 둥글다(캡슐형).
- 층 셋 너비(기본): 머리 19u, 몸 15u, 바닥 23u (왼쪽 정렬: 왼쪽 끝이 맞고 오른쪽 끝만 19u/15u/23u로 들쭉날쭉).
- 눈은 머리에만: 머리 왼쪽 끝에서 9u 지점에 왼쪽 눈(2u × 4u), 2u 간격을 두고 13u 지점에 오른쪽 눈(1.75u × 3.3u).
- 층 크기(19u·15u·23u, 8u·6u·6u, 간격 1u)는 어떤 상태에서도 바뀌지 않는다. 감정은 눈과 층의 밀림(offset)으로만 만든다.
  1. 기본(idle): 평소의 ro (왼쪽 정렬, 왼눈이 살짝 큰 두 눈)
  2. 기록 중(recording): 아래를 보며 바닥 층이 길어진다
  3. 집중(focus): 하나만 본다 (일자 눈 '— —')
  4. 불안(anxious): 눈이 작아지고 층이 좌우로 어긋난다
  5. 발견(discovery): 눈이 동그랗게 커지고 머리가 들린다(머리-몸 간격 확장)
  6. 풀어냄(resolved): 웃는 호('⌒ ⌒') 눈과 함께 바닥이 길게 뻗는다
"""
import atexit
import hashlib
import hmac
import json
import os
import re
import secrets
import shutil
import signal
import subprocess
import sys
import tempfile
import threading
import time
from collections import Counter
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlparse

from . import activity, config, designmetrics, engines, findeval, findui, fsutil, handoff, harden, log, mapper, organize, recall, records
from . import license as license_mod
from . import licensenet

STATE_WAIT_TIMEOUT = 20.0
STATE_WAIT_INTERVAL = 2.0

BLACK = "#1A1917"   # 먹 (Ink)
CREAM = "#F3EFE6"   # 분필 (Chalk)
MOODS = ("idle", "recording", "focus", "anxious", "discovery", "resolved")
MOOD_LABELS = {
    "idle": "Idle",
    "recording": "Recording",
    "focus": "Focus",
    "anxious": "Attention",
    "discovery": "Discovery",
    "resolved": "Resolved",
}
MOOD_CAPTIONS = {
    "idle": "Ro, as usual.",
    "recording": "Looks down.",
    "focus": "Sees only one thing.",
    "anxious": "Eyes shrink, layers slip.",
    "discovery": "Eyes widen, head lifts.",
    "resolved": "Smiles.",
}
MATERIALS = ("clay", "glass")
MATERIAL_LABELS = {
    "clay": "Clay",
    "glass": "Glass",
}
ACTIONS = (
    "breathe",
    "look_around",
    "walk",
    "thinking",
    "alert",
    "drowsy",
    "gaze",
    "pet",
    "drag",
    "shake",
    "drop",
    "success",
    "failure",
)
ACTION_LABELS = {
    "breathe": "Breathe",
    "look_around": "Look around",
    "walk": "Walk",
    "thinking": "Think",
    "alert": "Startle",
    "drowsy": "Drowsy",
    "gaze": "Gaze",
    "pet": "Pet",
    "drag": "Drag",
    "shake": "Shake",
    "drop": "Land",
    "success": "Success",
    "failure": "Failure",
}
ACTION_DESCS = {
    "breathe": "Three layers breathe out of phase (3 s loop)",
    "look_around": "Eyes lead the glance",
    "walk": "Base, body, head step in sequence",
    "thinking": "Head tilts, off-beat pulse",
    "alert": "Sudden hop, eyes widen",
    "drowsy": "Head sinks, squinting, deep breaths",
    "gaze": "Eyes follow the cursor",
    "pet": "Head presses down, leans in, smiles (rub the head)",
    "drag": "Stretches tall, base sags (drag)",
    "shake": "Layers sway side to side (quick shake)",
    "drop": "Landing squash and spring",
    "success": "Crouch, happy jump, smiling eyes",
    "failure": "Layers slip, tremble, tiny eyes",
}
RECORDING_WINDOW_SEC = 8.0
RESOLVED_WINDOW_SEC = 10.0
AUDIT_TTL_SEC = 30.0  # 로그·학습 파일이 그대로여도 권한·비밀값 감사는 이 주기로 다시 돈다
# ro 색(본문 Style)과 상태창 색(Settings)은 따로 고른다. 기본은 둘 다 시스템
PREF_CHOICES = {"material": ("clay", "glass"), "color": ("auto", "light", "dark", "orange"),
                "panel": ("auto", "light", "dark"), "size": ("small", "medium", "big"),
                "focus": (True, False), "lang": ("en", "ko")}
# 화면 언어. 기본은 영어. "source"는 번역하지 않은 원문(테스트가 원문 문구를 본다)이라 설정으로는 고를 수 없다
LANGS = ("en", "ko", "source")


def default_lang():
    lang = os.environ.get("RO_LANG", "en")
    return lang if lang in LANGS else "en"
# 에디션: "mini"(V1, 꾸미기 전용: 펫·재질·색·표정·모션만, 파일 기능 없음) / "pro"(V2, 기능 포함)
EDITIONS = ("mini", "pro")
MINI_API = ("/api/prefs", "/api/action", "/api/license")
RESTART_EXIT = 75  # 호스트가 이 코드로 끝나면 라이선스 변경을 적용하려고 다시 연다(pet_mac.swift finishLicense)  # mini 에디션에서 열어 두는 POST 경로


def default_edition():
    e = os.environ.get("RO_EDITION", "mini")
    return e if e in EDITIONS else "mini"


RECENT_MAX = 10
TIMELINE_MAX = 60
MAX_ACTION_SEC = 60.0  # 상호작용 한 번이 이어지는 최대 시간


# 정밀 그리드 기본 단위 (23u 만폭 기준 상대 비율: 19/23, 15/23, 23/23)
HEAD_U = 19
BODY_U = 15
BASE_U = 23


def _batch_when(batch):
    """배치 id(20261024-160545) → '10/24 16:05'. 형식이 다르면 그대로."""
    try:
        t = time.strptime(str(batch)[:15], "%Y%m%d-%H%M%S")
    except ValueError:
        return str(batch)
    return time.strftime("%m/%d %H:%M", t)


def layer_widths():
    """CONSTRUCTION 정밀 그리드: 머리 19u · 몸 15u · 바닥 23u (왼쪽 정렬). 어떤 상태에서도 바뀌지 않는다."""
    return {"head_u": HEAD_U, "body_u": BODY_U, "base_u": BASE_U}


def ambient_state(today_count, hour, focus=False, held=0, attention=False):
    """패널을 열지 않아도 알 수 있는 상태(시간대·오늘 기록 수·집중·확인 필요). 몸 크기는 바꾸지 않는다."""
    band = "Morning" if hour < 12 else ("Afternoon" if hour < 18 else "Evening")
    return {"band": band, "label": f"{band} · {today_count}",
            "focus": bool(focus), "held": int(held) if focus else 0, "attention": bool(attention)}


def layer_offsets(mood="idle"):
    """팔다리 대신 층이 밀리고 들려서 감정을 만드는 오프셋(px 단위 기준)."""
    if mood == "anxious":
        # 층이 어긋난다: 머리는 왼쪽, 몸은 오른쪽으로 밀림
        return {"head_x": -4, "head_y": 0, "body_x": 7, "base_x": 1}
    if mood == "discovery":
        # 머리가 들린다: 머리가 위로 올라감
        return {"head_x": 0, "head_y": -5, "body_x": 0, "base_x": 0}
    if mood == "focus":
        return {"head_x": 2, "head_y": 0, "body_x": 0, "base_x": 0}
    if mood == "resolved":
        return {"head_x": 0, "head_y": -2, "body_x": 0, "base_x": 0}
    return {"head_x": 0, "head_y": 0, "body_x": 0, "base_x": 0}


def clamp_pet_origin(x, y, width, height, screen_rect, margin=6):
    """펫 창이 화면 밖(특히 하단 Dock 아래나 상단 메뉴바 위)으로 벗어나지 않도록 좌표를 고정한다.
    screen_rect: (min_x, min_y, max_x, max_y)
    """
    min_x, min_y, max_x, max_y = screen_rect
    lo_x = min_x + margin
    hi_x = max(lo_x, max_x - width - margin)
    lo_y = min_y + margin
    hi_y = max(lo_y, max_y - height - margin)
    return (min(max(x, lo_x), hi_x), min(max(y, lo_y), hi_y))


def icon_16px_grid():
    """16x16 전용 아이콘 그리드(왼쪽 정렬, 머리 6px·몸 4px·바닥 4px·간격 1px,
    16px 이하 규칙: 눈 사이 간격 1px 확보, 눈 크기 1px 통일).
    """
    return [
        "                ",
        " ###########    ",
        "############    ",
        "#######.#.##    ",
        "############    ",
        "############    ",
        " ###########    ",
        "                ",
        " #########      ",
        "##########      ",
        "##########      ",
        " #########      ",
        "                ",
        " #############  ",
        "##############  ",
        " #############  ",
    ]


class PetRuntime:
    """펫의 실시간 상태(집중·풀어냄·쓰기 승인 대기)와 ~/.ro 상태를 결합한다."""

    def __init__(self, home=config.HOME, log_dir=log.LOG_DIR, map_path="~/.ro/map.json", edition=None):
        self.edition = edition if edition in EDITIONS else default_edition()
        self.home = home
        self.log_dir = log_dir
        self.map_path = map_path
        self.token = secrets.token_hex(16)
        self._lock = threading.Lock()
        self.resolved_until = 0.0
        self.recording_until = 0.0
        self.write_pending = None
        self._last_event_count = None
        self._disk_cache = None
        self.organize_root = organize.ROOT
        self.organize_dest = organize.DEST_ROOT
        self.current_action = None
        self.action_until = 0.0
        self.focus_on = False
        self._focus_base = 0
        self.finder = findui.FindSession(self.home)  # 파일 찾기: 결과 경로는 서버만 쥐고 화면에는 번호만 준다
        self.focus_on = bool(self.prefs().get("focus"))  # 재시작해도 집중 모드를 이어 간다
        # ro pro: 펫 호스트와 표준입출력 JSON-Lines로 센서·토스트를 주고받는다. mini는 만들지도 않는다
        self.tact = None
        self.hint = None             # 1단계: 상태 줄에만 보이는 사실 한 줄
        self.ax_trusted = None       # 호스트 ready 이벤트로 받는 Accessibility 권한 여부(True/False/None)
        self._nudges = {}            # 띄운 토스트 id → 트리거·데이터
        self.nudge_handlers = {}     # 트리거 → 수락 시 할 일(M3 시나리오가 등록)
        self._host_in = None
        self._host_lock = threading.Lock()
        self.pro = None
        self.restart_requested = False  # 라이선스로 에디션이 바뀌면 호스트가 끝난 뒤 같은 프로세스로 다시 연다
        self.force_restart = False      # 자동으로 받은 키로 mini→pro가 되면 묻지 않고 다시 연다(licensenet)
        self.on_force_restart = None    # launch가 호스트를 끝내는 함수를 걸어 둔다
        if self.edition == "pro":
            from . import prowatch, tact
            self.tact = tact.TactGate(self.home, self.log_dir)
            self.pro = prowatch.ProWatch(self)

    # ---- ro pro 호스트 파이프 ----
    SENSOR_TYPES = ("front", "idle", "capture", "fullscreen", "user_io", "ax")

    def attach_host(self, stdin):
        if self.edition == "pro":
            self._host_in = stdin

    def send_host(self, msg):
        """호스트로 한 줄. 파이프가 없거나 끊겼으면 False(펫이 멈추지 않게 조용히)."""
        if self.edition != "pro" or self._host_in is None:
            return False
        with self._host_lock:
            try:
                self._host_in.write(json.dumps(msg, ensure_ascii=False) + "\n")
                self._host_in.flush()
                return True
            except (OSError, ValueError):
                self._host_in = None
                return False

    def on_host_line(self, line):
        """호스트가 보낸 한 줄을 처리한다. JSON이 아니거나 모르는 줄은 버린다. 반환: 처리했는지."""
        if self.edition != "pro":
            return False
        try:
            ev = json.loads(line)
        except ValueError:
            return False
        if not isinstance(ev, dict):
            return False
        kind = ev.get("type")
        if kind == "ready":
            if isinstance(ev.get("ax"), bool):
                self.ax_trusted = ev["ax"]
            return True
        if kind in self.SENSOR_TYPES:
            activity.push(ev)
            if self.tact.on_sensor(ev) and kind == "front" and ev.get("app"):   # 비밀 앱은 위에서 이미 버렸다
                from . import profile
                at = ev.get("t") or time.time()
                profile.observe_quiet("app_band", profile.band(at), str(ev["app"]), home=self.home, now=at)
            elif kind == "ax" and self.tact.front and not self.tact.front.get("private"):
                self.pro.on_ax(ev, self.tact.front.get("app"), now=ev.get("t"))
            return True
        if kind == "toast_result" and ev.get("trigger") and ev.get("action") in ("accepted", "off", "ignored", "promote"):
            nid = ev.get("id")
            with self._lock:
                payload = self._nudges.pop(nid, None)
            if payload is None or payload["trigger"] != ev["trigger"]:
                return False   # 내가 띄운 적 없는 토스트의 결과는 받지 않는다
            action = "accepted" if ev["action"] == "promote" else ev["action"]
            self.tact.record(ev["trigger"], action)
            if ev["action"] == "off":
                prefs = config.load(self.home).get("nudges_off") or []
                if ev["trigger"] not in prefs:
                    config.update(self.home, nudges_off=prefs + [ev["trigger"]])
            elif action == "accepted":
                handler = self.nudge_handlers.get(ev["trigger"])
                if handler:   # 실제 일(카드 열기 등)은 트리거마다 등록한 쪽이 한다. 여기서는 파일을 건드리지 않는다
                    threading.Thread(target=handler, args=(payload["data"], ev["action"] == "promote"),
                                     daemon=True).start()
            return True
        return False

    # 질문·재촉 문구는 내보내지 않는다(디자인 원칙 4, 2026-11-16)
    NUDGE_BANNED = re.compile(r"[?？]|까요|할래요|드릴게요|해 보세요|아직 안|하셨나요|\b(?:want|should|shall|did you)\b", re.I)
    NUDGE_MAX = 80
    HINT_SECONDS = 4 * 3600

    def nudge(self, trigger, fact, verb, data=None, folder=None, now=None):
        """먼저 다가가기 한 번. fact는 사실 한 줄, verb는 '격리'처럼 동사·대상 버튼 글자.
        반환: (결정, 토스트 id). 2단계면 토스트, 1단계면 상태 줄 힌트, 그 밖에는 아무것도 하지 않는다."""
        if self.edition != "pro" or self.tact is None:
            return "quiet", None
        for text in (fact, verb):
            if not text or "\n" in text or len(text) > self.NUDGE_MAX or self.NUDGE_BANNED.search(text):
                raise ValueError("먼저 다가갈 때는 질문·재촉 없이 사실 한 줄만 씁니다")
        from . import tact
        now = time.time() if now is None else now
        decision, why = self.tact.decide(trigger, folder, now)
        if decision == tact.LEVEL2:
            nid = secrets.token_hex(6)
            ko = self.prefs().get("lang", "ko") == "ko"
            with self._lock:
                self._nudges[nid] = {"trigger": trigger, "data": data}
            if self.send_host({"cmd": "toast", "id": nid, "trigger": trigger, "text": fact, "verb": verb,
                               "off": "이 유형 끄기" if ko else "Turn off this type"}):
                self.tact.record(trigger, "shown", level=2, now=now)
                return decision, nid
            with self._lock:
                self._nudges.pop(nid, None)
            decision, why = tact.LEVEL1, "호스트 없음"   # 호스트가 없으면(브라우저 모드 등) 표정·상태 줄로 낮춘다
        if decision == tact.LEVEL1:
            with self._lock:
                self.hint = {"trigger": trigger, "text": fact, "verb": verb, "data": data, "until": now + self.HINT_SECONDS}
            self.tact.record(trigger, "shown", level=1, now=now, why=why)
        return decision, None

    # ---- pro 라이선스(docs/SITE-PLAN.md P2): 키는 이 Mac에서만 검사하고, 응답·로그에 키를 싣지 않는다 ----
    def license_api(self, data):
        act = data.get("action", "status")
        if act not in ("status", "set", "remove", "buy", "auto", "check"):
            return {"ok": False, "error": "Unsupported license action."}
        if act == "buy":   # 'Get pro…': 설치 토큰 해시를 실은 결제 주소. 호스트가 브라우저로 연다
            plan = data.get("plan")
            if plan not in licensenet.PLANS:
                return {"ok": False, "error": "Unsupported plan."}
            url = licensenet.buy_url(plan, self.home)
            if not url:
                return {"ok": False, "error": "자동 구매가 아직 준비되지 않았어요. 사이트에서 사면 키가 메일로 와요."}
            return {"ok": True, "url": url, "pending": True}
        if act == "auto":
            if not isinstance(data.get("on"), bool):
                return {"ok": False, "error": "on must be true or false."}
            licensenet.auto(data["on"], self.home)
        activated = False
        if act == "check":
            if licensenet.active(self.home):
                activated = licensenet.sync(self.home)
        if act == "set":
            key = data.get("key")
            if not isinstance(key, str):
                return {"ok": False, "error": "키가 비어 있습니다."}
            try:
                license_mod.save(key, self.home)
            except license_mod.LicenseError as exc:
                return {"ok": False, "error": str(exc), **license_mod.status(self.home)}
        elif act == "remove":
            license_mod.remove(self.home)
        st = license_mod.status(self.home)
        now_edition = "pro" if st["state"] == "valid" else "mini"
        # 번들 앱(실행기가 키로 에디션을 정할 때)만 다시 열어 바뀐 에디션을 적용한다. 개발 실행은 환경 변수가 정한다
        restart = ((act in ("set", "remove") or activated) and os.environ.get("RO_EDITION_SOURCE") == "license"
                   and now_edition != self.edition)
        if restart:
            self.restart_requested = True
        return {"ok": True, **st, "edition": self.edition, "restart": restart, "activated": activated,
                "pending": licensenet.pending(self.home),
                "auto": licensenet.auto(home=self.home), "autoReady": bool(licensenet._issuer())}

    def license_tick(self, now=None, fetch=None):
        """자동 받기 한 번: 연락할 때가 아니면 아무것도 안 한다. 새 키로 mini→pro가 되면 스스로 다시 연다."""
        if not licensenet.due(self.home, now, self.edition):
            return False
        got = licensenet.sync(self.home, now, **({"fetch": fetch} if fetch else {}))
        if (got and self.edition == "mini" and os.environ.get("RO_EDITION_SOURCE") == "license"
                and license_mod.edition(self.home) == "pro"):
            self.force_restart = True
            log.append("pet", "라이선스를 받아 pro로 다시 시작", {}, log_dir=self.log_dir)
            if self.on_force_restart:
                self.on_force_restart()
        return got

    # ---- ro가 배운 것(원칙 6): 보고·고정·끄고·지운다. 동의는 학습과 먼저 알림을 따로 받는다 ----
    LEARNED_OPS = ("list", "consent", "nudges", "type_on", "pin", "unpin", "off", "on", "forget", "wipe")

    def learned_api(self, data):
        from . import profile
        op = data.get("op", "list")
        if self.edition != "pro" or op not in self.LEARNED_OPS:
            return {"ok": False, "error": "알 수 없는 요청이에요."}
        if op in ("consent", "nudges"):
            if not isinstance(data.get("on"), bool):
                return {"ok": False, "error": "on은 true/false여야 해요."}
            if op == "consent":
                profile.set_consent(self.home, data["on"])
            else:
                config.update(self.home, pro_nudges=data["on"])
        elif op == "type_on":
            off = [t for t in (config.load(self.home).get("nudges_off") or []) if t != data.get("trigger")]
            config.update(self.home, nudges_off=off)
        elif op == "wipe":
            if data.get("approve") is not True:
                return {"ok": False, "error": "approve는 true여야 해요."}
            profile.wipe(self.home)
        elif op != "list":
            if type(data.get("id")) is not int:
                return {"ok": False, "error": "번호가 올바르지 않아요."}
            done = {"pin": lambda i: profile.pin(i, True, self.home), "unpin": lambda i: profile.pin(i, False, self.home),
                    "off": lambda i: profile.turn_off(i, True, self.home),
                    "on": lambda i: profile.turn_off(i, False, self.home),
                    "forget": lambda i: profile.forget(i, self.home)}[op](data["id"])
            if not done:
                return {"ok": False, "error": "그 항목을 찾지 못했어요."}
        cfg = config.load(self.home)
        counts = designmetrics.nudges(self.log_dir)
        verdict = designmetrics.nudge_verdicts(counts)
        shown = sum(c["노출"] for c in counts.values())
        kept = sum(c["수락"] - c["24시간 안 되돌림"] for c in counts.values())
        metrics = {"shown": shown, "help": round(kept / shown, 2) if shown else None,
                   "off": round(sum(c["끄기"] for c in counts.values()) / shown, 2) if shown else None,
                   "overall": verdict.pop("원칙4 전체"),
                   "demoted": sorted(t for t, v in verdict.items() if v == "1단계로 강등")}
        return {"ok": True, "metrics": metrics, "learning": cfg.get(profile.CONSENT) is True, "nudges": cfg.get("pro_nudges") is True,
                "nudges_off": list(cfg.get("nudges_off") or []), "items": profile.learned(self.home)}

    def trigger_action(self, action, duration=4.0):
        """모션 상호작용(ACTIONS: 숨쉬기·두리번·걷기·생각·깜짝·졸음·시선·누름·쓰다듬기·끌기·흔들기·착지·성공·실패)을 즉시 발동한다."""
        if action not in ACTIONS:
            return {"ok": False, "error": f"Unsupported interaction: {action}"}
        try:
            duration = float(duration)
        except (TypeError, ValueError):
            return {"ok": False, "error": "duration은 숫자여야 합니다."}
        if not 0 < duration <= MAX_ACTION_SEC:  # inf·nan이면 동작이 풀리지 않고 응답 JSON도 깨진다
            return {"ok": False, "error": f"duration은 0초 초과 {MAX_ACTION_SEC}초 이하여야 합니다."}
        now = time.time()
        with self._lock:
            self.current_action = action
            self.action_until = now + duration
        return {
            "ok": True,
            "action": action,
            "duration": duration,
            "label": ACTION_LABELS.get(action, action),
            "desc": ACTION_DESCS.get(action, "")
        }

    def mark_recording(self, now=None):
        now = now or time.time()
        with self._lock:
            self.recording_until = now + RECORDING_WINDOW_SEC

    def _projects(self):
        return (mapper.load_map(self.map_path, self.home) or {}).get("projects", [])

    def prefs(self):
        """펫 화면 설정(재질·색·집중). ~/.ro/config.json의 "pet" 항목. 없어진 설정(옛 색 등)은 읽지 않는다."""
        p = config.load(self.home).get("pet")
        return {k: v for k, v in p.items() if k in PREF_CHOICES} if isinstance(p, dict) else {}

    def set_prefs(self, changes):
        clean = {k: v for k, v in (changes or {}).items() if v in PREF_CHOICES.get(k, ())}
        if not clean:
            return {"ok": False, "error": "That setting cannot be saved."}
        config.update(self.home, pet={**self.prefs(), **clean})
        return {"ok": True, "prefs": self.prefs()}

    def set_focus(self, on):
        today = time.strftime("%Y-%m-%d")
        with self._lock:
            self.focus_on = bool(on)
            self._focus_base = len([e for e in records.live(log.read(today, self.log_dir))
                                    if records.is_user_record(e)])
        self.set_prefs({"focus": self.focus_on})
        return {"ok": True, "focus": self.focus_on}

    def recall_question(self, question):
        return recall.answer(question, log.read_all(self.log_dir), self._projects(), home=self.home)

    def capture(self, kind, name, text, size):
        return records.capture(kind, name, text, size, self._projects(), log_dir=self.log_dir)

    def capture_undo(self, target_id):
        return records.revoke(str(target_id or ""), log_dir=self.log_dir)

    def capture_project(self, target_id, project):
        names = {p["name"] for p in self._projects()}
        project = project or ""  # 빈 값 = '분류 없음'으로 해제
        if project and project not in names:
            return {"ok": False, "error": "알 수 없는 프로젝트예요."}
        events = log.read_all(self.log_dir)
        if str(target_id) not in {records.eid(e) for e in events}:
            return {"ok": False, "error": "해당 기록을 찾을 수 없어요."}
        records._write({"batch": f"m{int(time.time())}-{secrets.token_hex(3)}", "ts": time.time(),
                        "assign": {str(target_id): project}}, self.home)
        return {"ok": True, "project": project or None}

    def records_plan(self):
        return records.plan(records.live(log.read_all(self.log_dir)), self._projects(), home=self.home)

    def records_apply(self, picks):
        picks = picks if isinstance(picks, dict) else {}
        return records.apply(log.read_all(self.log_dir), self._projects(), picks, home=self.home)

    def records_undo(self):
        return records.undo(home=self.home)

    def resolve_write_approval(self, approve_write, pending_id=None):
        """pending_id가 지금 대기 중인 요청과 같을 때만 그 요청을 소비한다(다른 창에서 바뀐 요청을 실행하지 않는다)."""
        with self._lock:
            item = self.write_pending
            if not item:
                return {"ok": False, "output": "대기 중인 쓰기 요청이 없습니다."}
            if pending_id != item["id"]:
                return {"ok": False, "reason": "stale",
                        "output": "확인 카드가 바뀌었어요. 지금 보이는 요청을 다시 확인해 주세요."}
            self.write_pending = None
        if not approve_write:
            log.append("write_gate", f"쓰기 거절: {item['task']}", {"engine": item["engine"]},
                       engine=item["engine"], log_dir=self.log_dir)
            return {"ok": True, "approved": False, "output": "쓰기 작업을 취소했습니다."}
        if item.get("kind") in ("organize_apply", "organize_undo"):
            return self._run_organize(item)
        return {"ok": False, "approved": False, "output": "지원하지 않는 쓰기 요청이라 실행하지 않았어요."}

    # ---------- 파일 정리(organize): scan은 바로, 이동·되돌리기는 쓰기 승인 게이트를 거친다 ----------
    def organize_summary(self):
        """현재 정리안의 카테고리별 건수(검토 필요 제외)와 되돌릴 수 있는 마지막 배치. 정리안이 없으면 None."""
        try:
            plan = organize.load_plan(self.home)
        except ValueError:
            return None
        moves = organize.pending(self.home, sources=("cleanup", "organize"))  # tidy 기록은 펫 되돌리기에 넣지 않는다
        moved = self._moved_keys(moves)  # 이미 옮긴·격리한(되돌리지 않은) 그 파일은 다시 세지 않는다
        ready = Counter(i["category"] for i in plan["items"] if organize.movable(i) and (i["id"], i["sha"]) not in moved)
        # 치울 후보: 검토 필요(재무·계약 중복)는 펫에서 승인할 수 없으니 묶음에서 뺀다
        q_n, q_bytes = Counter(), Counter()
        for i in plan["items"]:
            if i.get("action") == "quarantine" and not i["review"] and (i["id"], i["sha"]) not in moved:
                q_n[i["kind"]] += 1
                q_bytes[i["kind"]] += i["size"]
        _, trashed = organize.trash_size(self.home)
        last = moves[-1]["batch"] if moves else None
        review = [i for i in plan["items"] if i["review"] and i.get("action", "move") != "keep"]
        return {
            "created": plan["created"],
            "dest_root": findeval.display_path(plan["dest_root"]),
            "counts": [[c, ready[c]] for c in organize.CATEGORIES if ready[c]],
            "quarantine": [[k, organize.KIND_LABELS.get(k, k), q_n[k], q_bytes[k]] for k in q_n],
            "reclaim": sum(q_bytes.values()),
            "trashed": trashed,
            "review": len(review),
            "review_names": [Path(i["path"]).name for i in review[:10]],
            "recent_skipped": plan.get("recent_skipped", 0),
            "total": len(plan["items"]),
            "undo": {"batch": last, "count": sum(e["batch"] == last for e in moves),
                     "when": _batch_when(last)} if last else None,
        }

    @staticmethod
    def _fingerprint(items):
        """승인한 항목 그대로인지 대조할 지문(id·원래 경로·새 경로·내용 해시·처리 방식)."""
        rows = sorted((i["id"], i["path"], i.get("dest"), i["sha"], i.get("action", "move"), i.get("category"))
                      for i in items)
        return hashlib.sha256(json.dumps(rows, ensure_ascii=False).encode()).hexdigest()[:16]

    @staticmethod
    def _moved_keys(moves):
        """옮긴 항목의 (id, 내용 해시). id는 원래 경로에서 나오므로, 같은 자리에 새로 생긴 다른 파일은 빼지 않는다."""
        return {(e["id"], e.get("sha")) for e in moves}

    def _picked(self, plan, category=None, kind=None):
        moved = self._moved_keys(organize.pending(self.home, sources=("cleanup", "organize")))
        if kind:
            return [i for i in plan["items"] if i.get("action") == "quarantine" and i.get("kind") == kind
                    and not i["review"] and (i["id"], i["sha"]) not in moved]
        return [i for i in plan["items"] if organize.movable(i) and i["category"] == category
                and (i["id"], i["sha"]) not in moved]

    def _plan_files(self, category=None, kind=None):
        """승인 카드에 보여 줄 모든 파일(원래 이름 → 새 이름)과 승인 범위(id 목록·지문).
        보여 준 것과 실행하는 것이 같아야 하므로 목록을 자르지 않는다."""
        try:
            plan = organize.load_plan(self.home)
        except ValueError:
            return [], [], ""
        picked = self._picked(plan, category, kind)
        files = [{"from": Path(i["path"]).name, "to": None if kind else Path(i["dest"]).name} for i in picked]
        return files, [i["id"] for i in picked], self._fingerprint(picked)

    def organize_scan(self):
        """읽기 전용 스캔으로 정리안을 새로 만든다. 파일은 옮기지 않는다."""
        try:
            plan = organize.scan(self.organize_root, self.organize_dest, home=self.home)
        except (OSError, ValueError) as e:
            return {"ok": False, "output": str(e)}
        organize.save_plan(plan, self.home)
        log.append("organize_scan", f"정리안 {len(plan['items'])}건", {
            "count": len(plan["items"]), "review": sum(i["review"] for i in plan["items"]), "via": "pet"},
            log_dir=self.log_dir)
        return {"ok": True, "organize": self.organize_summary()}

    def _queue(self, item):
        item = {"id": secrets.token_hex(4), "engine": "ro organize", "cwd": None, **item}
        with self._lock:
            self.write_pending = item
        return {"ok": True, "pending": item}

    def queue_organize_apply(self, category=None, kind=None):
        """카테고리 이동(category) 또는 치울 후보 격리(kind)를 바로 하지 않고 쓰기 승인 대기열에 올린다."""
        summary = self.organize_summary()
        if kind:
            group = next((g for g in (summary or {}).get("quarantine", []) if g[0] == kind), None)
            if not group:
                return {"ok": False, "output": "이 종류의 치울 후보가 없습니다. 정리안을 먼저 만드세요."}
            _, label, n, size = group
            files, ids, fp = self._plan_files(kind=kind)
            return self._queue({"kind": "organize_apply", "category": None, "qkind": kind, "count": len(ids),
                                "plan_created": summary["created"], "ids": ids, "fingerprint": fp,
                                "files": files, "more": 0,
                                "task": f"{label} {n}건({organize._mb(size)})을 보관함(~/.ro/cleanup/trash)으로 "
                                        "옮깁니다. 지우지 않고, 되돌릴 수 있어요."})
        n = dict(map(tuple, summary["counts"])).get(category, 0) if summary else 0
        if not n:
            return {"ok": False, "output": "이 카테고리에 옮길 항목이 없습니다. 정리안을 먼저 만드세요."}
        files, ids, fp = self._plan_files(category=category)
        return self._queue({"kind": "organize_apply", "category": category, "count": len(ids),
                            "plan_created": summary["created"], "ids": ids, "fingerprint": fp,
                            "files": files, "more": 0,
                            "task": f"파일 정리: {category} {n}건을 {summary['dest_root']}/{category}로 옮기고 "
                                    "이름을 바꿉니다."})

    def queue_organize_undo(self):
        summary = self.organize_summary()
        undo = summary and summary["undo"]
        if not undo:
            return {"ok": False, "output": "되돌릴 정리 기록이 없습니다."}
        return self._queue({"kind": "organize_undo", "batch": undo["batch"], "count": undo["count"],
                            "task": f"{undo['when']}에 정리한 {undo['count']}건을 원래 이름·위치로 되돌립니다."})

    def _run_organize(self, item):
        try:
            if item["kind"] == "organize_apply":
                plan = organize.load_plan(self.home)
                now = self._picked(plan, item.get("category"), item.get("qkind"))
                if (plan["created"] != item["plan_created"] or sorted(i["id"] for i in now) != sorted(item["ids"])
                        or self._fingerprint(now) != item["fingerprint"]):
                    raise ValueError("승인 요청 뒤에 정리안이 바뀌었습니다(파일·이름·위치). 다시 요청하세요.")
                # 카테고리 전체가 아니라 확인 카드에 보여 준 그 항목들만 처리한다
                batch, done, skipped = organize.apply(ids=item["ids"], home=self.home, log_dir=self.log_dir)
                if item.get("qkind"):
                    label = organize.KIND_LABELS.get(item["qkind"], item["qkind"])
                    output = f"{label} {len(done)}건 격리 (되돌리기 가능, 삭제 아님)"
                else:
                    output = f"{item['category']} {len(done)}건 이동 (되돌리기 가능)"
            else:
                batch, done, skipped = organize.undo(item["batch"], self.home, self.log_dir)
                output = f"{len(done)}건을 원래 자리로 되돌림"
        except (OSError, ValueError) as e:
            return {"ok": False, "approved": True, "output": str(e)}
        if item["kind"] == "organize_apply":
            names = {i["id"]: Path(i["path"]).name for i in plan["items"]}
        else:
            names = {e["id"]: Path(e["src"]).name for e in organize.read_journal(self.home)
                     if e.get("batch") == item.get("batch")}
        skipped_rows = [{"name": names.get(cid, cid), "reason": why} for cid, why in skipped]
        if skipped:
            output += f", 건너뜀 {len(skipped)}건"
        status = "complete" if done and not skipped else "partial" if done else "skipped"
        if done:  # 아무것도 처리하지 못했으면 '해결' 표정을 짓지 않는다
            with self._lock:
                self.resolved_until = time.time() + RESOLVED_WINDOW_SEC
        return {"ok": bool(done), "approved": True, "batch": batch, "output": output, "status": status,
                "done": len(done), "skipped": skipped_rows}

    def _disk_signature(self):
        """로그·학습 파일의 (이름, 크기, mtime, ctime). 바뀌지 않았으면 다시 읽을 필요가 없다."""
        sig = []
        for folder, pattern in ((self.log_dir, "*.jsonl"), (self.home, "*.json")):
            for p in sorted(Path(folder).expanduser().glob(pattern)):
                try:
                    st = p.stat()
                except OSError:
                    continue
                sig.append((str(p), st.st_size, st.st_mtime_ns, st.st_ctime_ns))
        return tuple(sig)

    def _disk_state(self, day):
        """450ms 폴링마다 전체 로그 파싱·pending.json 쓰기·감사를 반복하지 않도록 파일이 바뀔 때만 다시 계산한다."""
        sig = self._disk_signature()
        cached = self._disk_cache
        mono = time.monotonic()
        if cached and cached[0] == (day, sig) and mono - cached[1] < AUDIT_TTL_SEC:
            return cached[2]
        today_events = records.live(log.read(day, self.log_dir))
        findings, _ = harden.audit(self.home, fix=False)
        state = (today_events, findings)
        self._disk_cache = ((day, self._disk_signature()), mono, state)
        return state

    def snapshot(self, now=None):
        """현재 ~/.ro 로그·감사 결과와 런타임 상태를 종합해 펫 상태를 계산한다."""
        now = now or time.time()
        material = self.prefs().get("material", "clay")
        material = material if material in MATERIALS else "clay"
        if self.edition == "mini":
            with self._lock:
                active_action = self.current_action if now < self.action_until else None
            hour = time.localtime(now).tm_hour
            band = "Morning" if hour < 12 else ("Afternoon" if hour < 18 else "Evening")
            mood = "idle"
            return {
                "mood": mood,
                "mood_label": MOOD_LABELS[mood],
                "mood_caption": MOOD_CAPTIONS[mood],
                "action": active_action,
                "action_label": ACTION_LABELS.get(active_action) if active_action else None,
                "action_desc": ACTION_DESCS.get(active_action) if active_action else None,
                "material": material,
                "material_label": MATERIAL_LABELS[material],
                "status_line": MOOD_CAPTIONS[mood],
                "layers": layer_widths(),
                "ambient": {"band": band, "label": band, "focus": False, "held": 0, "attention": False},
                "offsets": layer_offsets(mood),
                "health": "ok",
                "counts": {"today_events": 0, "today_records": 0, "projects": 0, "audit_findings": 0},
                "project_names": [],
                "write_pending": None,
                "organize": None,
                "audit_findings": [],
                "recent_logs": [],
                "timeline": [],
                "prefs": self.prefs(),
                "stats": [],
                "attention_items": [],
                "colors": {"black": BLACK, "cream": CREAM},
            }

        day = time.strftime("%Y-%m-%d", time.localtime(now))
        today_events, findings = self._disk_state(day)
        user_today = [e for e in today_events if records.is_user_record(e)]  # 펫 시작·스캔·질문은 기록이 아니다
        visible_events = [e for e in today_events if e.get("kind") != "pet_error"]
        mapdata = mapper.load_map(self.map_path, self.home)
        projects = (mapdata or {}).get("projects", [])

        with self._lock:
            if self._last_event_count is not None and len(user_today) > self._last_event_count:
                self.recording_until = max(self.recording_until, now + RECORDING_WINDOW_SEC)
            self._last_event_count = len(user_today)
            write_pending = self.write_pending
            hint = self.hint if self.hint and now < self.hint["until"] else None
            resolved_until = self.resolved_until
            recording_until = self.recording_until
            active_action = self.current_action if now < self.action_until else None

        alarm = findings
        if write_pending:
            mood = "focus"  # 내가 건 승인 요청은 사고가 아니다. 불안 대신 한 곳(확인 카드)을 본다
            status_line = f"실행 전 확인이 필요해요: {write_pending['task']}"
        elif alarm:
            mood = "anxious"
            status_line = findings[0]
        elif now < resolved_until:
            mood = "resolved"
            status_line = "기록하고, 풀어냈습니다."
        elif now < recording_until:
            mood = "recording"
            last_sum = user_today[-1]["summary"] if user_today else "새 기록"
            status_line = f"기록 중... ({last_sum})"
        else:
            mood = "idle"
            status_line = f"오늘 {len(user_today)}건 기록 · 프로젝트 {len(projects)}개"

        assigned = records.assignments(self.home)

        def row(e):
            out = {"id": records.eid(e), "ts": e.get("ts", "")[11:19], "kind": e.get("kind", ""),
                   "kind_label": records.kind_label(e.get("kind", "")),
                   "summary": log.redact(str(e.get("summary", "")))}
            if e.get("kind") == "organize":  # '정리 2건'만으로는 무엇을 옮겼는지 알 수 없다
                data = e.get("data") or {}
                parts = [f"{c} {n}" for c, n in (data.get("categories") or {}).items()]
                if data.get("quarantined"):
                    parts.append(f"보관함 {data['quarantined']}")
                if parts:
                    out["detail"] = log.redact(" · ".join(parts))
            if e.get("kind") == "note":
                out["project"] = records.project_of(e, assigned)
                out["excerpt"] = log.redact(list((e.get("data") or {}).get("excerpt") or []))[:3]
            return out

        recent_logs = [row(e) for e in user_today[-RECENT_MAX:]]
        timeline = [row(e) for e in visible_events[-TIMELINE_MAX:]]
        stats = Counter(records.kind_label(e.get("kind", "")) for e in visible_events).most_common()
        return {
            "mood": mood,
            "mood_label": MOOD_LABELS[mood],
            "mood_caption": MOOD_CAPTIONS[mood],
            "action": active_action,
            "action_label": ACTION_LABELS.get(active_action) if active_action else None,
            "action_desc": ACTION_DESCS.get(active_action) if active_action else None,
            "material": material,
            "material_label": MATERIAL_LABELS[material],
            "status_line": log.redact(hint["text"] if hint else status_line),
            "hint": {"trigger": hint["trigger"], "text": log.redact(hint["text"]), "verb": hint["verb"]} if hint else None,
            "pro": self.pro.snapshot() if self.pro else None,
            "layers": layer_widths(),
            "ambient": ambient_state(
                len(user_today), time.localtime(now).tm_hour, focus=self.focus_on,
                held=max(0, len(user_today) - self._focus_base),
                attention=bool(write_pending or alarm)),
            "offsets": layer_offsets(mood),
            "health": "attention" if findings else "ok",
            "counts": {
                "today_events": len(visible_events),
                "today_records": len(user_today),
                "projects": len(projects),
                "audit_findings": len(findings),
            },
            "project_names": [p["name"] for p in projects][:40],
            "write_pending": log.redact(write_pending) if write_pending else None,
            "organize": self.organize_summary(),
            "audit_findings": [log.redact(f) for f in findings[:3]],
            "recent_logs": recent_logs,
            "timeline": timeline,
            "prefs": self.prefs(),
            "stats": stats,
            "attention_items": self._attention_items(findings),
            "colors": {"black": BLACK, "cream": CREAM},
        }

    @staticmethod
    def _attention_items(findings):
        """'확인할 일'의 실제 내용과 다음 행동. 펫이 고치지는 않는다(권한 자동 수정 없음)."""
        items = []
        for f in findings[:5]:
            do = "ro audit --fix" if f.startswith("권한 과다") else "ro audit"
            items.append({"what": log.redact(f).replace(str(Path.home()), "~"), "do": do})
        return items


UI_DIR = Path(__file__).with_name("pet_ui")  # 화면(디자인)은 여기, 이 파일은 기능만


def load_pet_html(ui_dir=UI_DIR):
    """pet_ui/의 pet.html 틀에 pet.css·pet.js를 끼워 한 페이지로 만든다. 서버는 이 한 장만 내보낸다."""
    tpl = (ui_dir / "pet.html").read_text(encoding="utf-8")
    css = (ui_dir / "pet.css").read_text(encoding="utf-8")
    js = (ui_dir / "i18n.js").read_text(encoding="utf-8") + "\n" + (ui_dir / "pet.js").read_text(encoding="utf-8")
    return tpl.replace("__RO_CSS__", css, 1).replace("__RO_JS__", js, 1)


PET_HTML = load_pet_html()


def render_html(token, prefs=None, edition="mini"):
    """토큰과 저장된 화면 설정(재질·색·크기)을 넣어 페이지를 만든다. 설정은 고정 선택지만 통과시킨다."""
    p = {k: v for k, v in (prefs or {}).items()
         if k in ("material", "color", "panel", "size", "lang") and v in PREF_CHOICES[k]}
    ed = edition if edition in EDITIONS else "mini"
    lang = p.pop("lang", None) or default_lang()  # 언어는 __RO_LANG__ 한 곳으로만 넘긴다
    return (PET_HTML.replace("__RO_TOKEN__", token).replace("__RO_PREFS__", json.dumps(p))
            .replace("__RO_EDITION__", ed).replace("__RO_LANG__", lang))


def make_handler(runtime):
    class Handler(BaseHTTPRequestHandler):
        def log_message(self, fmt, *args):
            return

        def _send_json(self, status, payload):
            body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
            self.send_response(status)
            self.send_header("Content-Type", "application/json; charset=utf-8")
            self.send_header("Cache-Control", "no-store")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def _host_ok(self):
            # DNS 리바인딩 차단: 다른 도메인 이름으로 들어온 요청은 토큰이 박힌 페이지조차 내주지 않는다
            port = self.server.server_address[1]
            if self.headers.get("Host", "") in (f"127.0.0.1:{port}", f"localhost:{port}"):
                return True
            self._send_json(403, {"ok": False, "error": "invalid host"})
            return False

        def _token_ok(self):
            if hmac.compare_digest(self.headers.get("X-Ro-Token", ""), runtime.token):
                return True
            self._send_json(403, {"ok": False, "error": "invalid token"})
            return False

        def _guarded(self, fn):
            # 처리 중 예외가 나도 연결을 끊지 말고 JSON 500으로 알린다(본문에는 예외 종류만, 경로·내용은 싣지 않음)
            try:
                fn()
            except Exception as e:
                try:  # 나중에 원인을 찾을 수 있게 경로·예외 종류만 남긴다(요청 본문·메시지는 남기지 않음)
                    log.append("pet_error", f"{urlparse(self.path).path} {type(e).__name__}",
                               {"path": urlparse(self.path).path, "error": type(e).__name__}, log_dir=runtime.log_dir)
                except OSError:
                    pass
                try:
                    self._send_json(500, {"ok": False, "error": f"server error: {type(e).__name__}"})
                except OSError:
                    pass

        def do_GET(self):
            self._guarded(self._get)

        def do_POST(self):
            self._guarded(self._post)

        def _get(self):
            if not self._host_ok():
                return
            parsed = urlparse(self.path)
            if parsed.path == "/":
                body = render_html(runtime.token, runtime.prefs(), runtime.edition).encode("utf-8")
                self.send_response(200)
                self.send_header("Content-Type", "text/html; charset=utf-8")
                self.send_header("Cache-Control", "no-store")
                self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                self.wfile.write(body)
            elif parsed.path == "/api/state":
                if self._token_ok():
                    wait = parse_qs(parsed.query).get("wait", [None])[0]
                    deadline = time.monotonic() + STATE_WAIT_TIMEOUT
                    while True:
                        snapshot = runtime.snapshot()
                        version = hashlib.sha256(json.dumps(snapshot, sort_keys=True).encode("utf-8")).hexdigest()[:16]
                        remaining = deadline - time.monotonic()
                        if wait != version or remaining <= 0:
                            try:
                                self._send_json(200, {**snapshot, "version": version})
                            except (BrokenPipeError, ConnectionResetError):
                                pass  # 말풍선 전환으로 취소된 롱폴링은 오류 기록을 만들지 않는다.
                            break
                        time.sleep(min(STATE_WAIT_INTERVAL, remaining))
            else:
                self._send_json(404, {"error": "not found"})

        def _post(self):
            if not (self._host_ok() and self._token_ok()):
                return
            try:
                length = int(self.headers.get("Content-Length", "0") or "0")
            except ValueError:
                self._send_json(400, {"ok": False, "error": "Invalid Content-Length."})
                return
            if length < 0:
                self._send_json(400, {"ok": False, "error": "Invalid Content-Length."})
                return
            raw = self.rfile.read(min(length, 32768)).decode("utf-8", errors="replace")
            try:
                data = json.loads(raw) if raw else {}
            except json.JSONDecodeError:
                self._send_json(400, {"ok": False, "error": "invalid json"})
                return
            if not isinstance(data, dict):  # 배열·숫자 본문은 500이 아니라 잘못된 요청이다
                self._send_json(400, {"ok": False, "error": "A JSON object is required."})
                return

            parsed = urlparse(self.path)
            if runtime.edition == "mini" and parsed.path not in MINI_API:
                self._send_json(403, {"ok": False, "error": "Not available in Mini."})
            elif parsed.path == "/api/write_gate":
                if not isinstance(data.get("approve"), bool):  # "false" 같은 문자열을 승인으로 읽지 않는다
                    self._send_json(400, {"ok": False, "error": "approve는 true/false여야 합니다."})
                else:
                    self._send_json(200, runtime.resolve_write_approval(data["approve"], data.get("id")))
            elif parsed.path == "/api/recall":
                question = data.get("question", "")
                if not isinstance(question, str):  # 숫자·배열 질문은 500이 아니라 잘못된 요청이다(RO-AUD-105)
                    self._send_json(400, {"ok": False, "error": "question은 문자열이어야 합니다."})
                else:
                    self._send_json(200, runtime.recall_question(question))
            elif parsed.path == "/api/find":
                q, body_flag = data.get("question"), data.get("body")
                bad_input = (not isinstance(q, str) or not q.strip() or len(q.strip()) > findui.MAX_QUESTION
                             or (body_flag is not None and not isinstance(body_flag, bool)))
                res = runtime.finder.search(q, body_flag)
                self._send_json(400 if bad_input and not res.get("ok") else 200, res)
            elif parsed.path == "/api/find/open":
                if type(data.get("rank")) is not int:
                    self._send_json(400, {"ok": False, "error": "번호가 올바르지 않아요."})
                else:
                    self._send_json(200, runtime.finder.open(data["rank"], data.get("reveal") is True))
            elif parsed.path == "/api/find/pick":
                rank, answer = data.get("rank"), data.get("answer")
                bad_input = (("rank" in data and rank is not None and type(rank) is not int)
                             or ("answer" in data and answer is not None
                                 and (not isinstance(answer, str) or not answer.strip() or len(answer) > 1024)))
                res = runtime.finder.pick(rank, answer)
                self._send_json(400 if bad_input and not res.get("ok") else 200, res)
            elif parsed.path == "/api/find/signals":
                if data.get("later") is True:
                    self._send_json(200, runtime.finder.dismiss_consent())
                else:
                    res = runtime.finder.signals(data.get("on"))
                    status = 400 if not isinstance(data.get("on"), bool) and not res.get("ok") else 200
                    self._send_json(status, res)
            elif parsed.path == "/api/capture":
                kind = data.get("kind", "")
                res = runtime.capture(kind, data.get("name", ""), data.get("text", ""), data.get("size", 0))
                status = 400 if kind not in ("link", "file", "text") and not res.get("ok") else 200
                self._send_json(status, res)
            elif parsed.path == "/api/capture_undo":
                self._send_json(200, runtime.capture_undo(data.get("id")))
            elif parsed.path == "/api/capture_project":
                self._send_json(200, runtime.capture_project(data.get("id"), data.get("project")))
            elif parsed.path == "/api/records/plan":
                self._send_json(200, runtime.records_plan())
            elif parsed.path == "/api/records/apply":
                self._send_json(200, runtime.records_apply(data.get("picks")))
            elif parsed.path == "/api/records/undo":
                self._send_json(200, runtime.records_undo())
            elif parsed.path == "/api/organize/scan":
                self._send_json(200, runtime.organize_scan())
            elif parsed.path == "/api/organize/apply":
                kind = str(data.get("kind") or "")
                if kind and kind not in organize.QUARANTINE_KINDS:
                    self._send_json(400, {"ok": False, "output": "알 수 없는 종류"})
                else:
                    self._send_json(200, runtime.queue_organize_apply(str(data.get("category") or "") or None,
                                                                      kind or None))
            elif parsed.path == "/api/organize/files":  # 읽기만: 승인 요청을 걸지 않고 무엇이 옮겨질지 본다
                kind = str(data.get("kind") or "")
                files, _, _ = runtime._plan_files(category=str(data.get("category") or "") or None, kind=kind or None)
                self._send_json(200, {"ok": True, "files": log.redact(files)})
            elif parsed.path == "/api/organize/undo":
                self._send_json(200, runtime.queue_organize_undo())
            elif parsed.path == "/api/prefs":
                res = runtime.set_prefs(data)
                self._send_json(200 if res.get("ok") else 400, res)
            elif parsed.path == "/api/focus":
                if not isinstance(data.get("on"), bool):
                    self._send_json(400, {"ok": False, "error": "on must be true or false."})
                else:
                    self._send_json(200, runtime.set_focus(data["on"]))
            elif parsed.path == "/api/engines":
                self._send_json(200, {"ok": True, "engines": engines.status()})
            elif parsed.path == "/api/engines/plan":
                self._send_json(200, engines.connect_plan())
            elif parsed.path == "/api/engines/connect":
                if data.get("approve") is not True:
                    self._send_json(400, {"ok": False, "error": "approve는 true여야 합니다."})
                else:
                    self._send_json(200, engines.connect_apply(str(data.get("id") or "")))
            elif parsed.path == "/api/engines/undo":
                self._send_json(200, engines.connect_undo())
            elif parsed.path == "/api/activity":
                act = data.get("action", "status")
                if act not in ("status", "on", "off", "pause"):
                    self._send_json(400, {"ok": False, "error": "Unsupported activity action."})
                else:
                    if act == "on":
                        activity.turn_on()
                    elif act == "off":
                        activity.turn_off()
                    elif act == "pause":
                        activity.pause(60)
                    self._send_json(200, {"ok": True, **activity.report()})
            elif parsed.path == "/api/handoff/plan":
                self._send_json(200, handoff.plan_for_pet(str(data.get("arg") or ""), str(data.get("session") or "")))
            elif parsed.path == "/api/handoff/preview":
                self._send_json(200, handoff.preview_for_pet(str(data.get("id") or "")))
            elif parsed.path == "/api/handoff/apply":
                if data.get("approve") is not True:
                    self._send_json(400, {"ok": False, "error": "approve는 true여야 합니다."})
                else:
                    self._send_json(200, handoff.apply_for_pet(str(data.get("id") or "")))
            elif parsed.path == "/api/engines/handoff":
                res = engines.handoff(str(data.get("id") or ""), str(data.get("text") or ""))
                self._send_json(400 if res.get("error") == "알 수 없는 도구예요." else 200, res)
            elif parsed.path == "/api/stage":
                res = runtime.pro.api(data) if runtime.pro else {"ok": False, "error": "ro pro 전용이에요."}
                self._send_json(200 if res.get("ok") else 400, res)
            elif parsed.path == "/api/license":
                res = runtime.license_api(data)
                self._send_json(200 if res.get("ok") else 400, res)
            elif parsed.path == "/api/memory":
                res = runtime.learned_api(data)
                self._send_json(200 if res.get("ok") else 400, res)
            elif parsed.path == "/api/action":
                act = data.get("action") or data.get("name", "")
                res = runtime.trigger_action(act, data.get("duration", 4.0))
                self._send_json(200 if res.get("ok") else 400, res)
            else:
                self._send_json(404, {"ok": False, "error": "not found"})

    return Handler


def start_server(runtime, host="127.0.0.1", port=0):
    """로컬 루프백(127.0.0.1)에만 바인딩하는 HTTP 서버를 시작한다."""
    if host not in ("127.0.0.1", "localhost"):
        raise ValueError("pet 서버는 127.0.0.1(로컬 전용)에만 바인딩할 수 있습니다.")
    # ThreadingHTTPServer.daemon_threads=True: 롱폴링이 종료를 붙잡지 않는다.
    server = ThreadingHTTPServer(("127.0.0.1", port), make_handler(runtime))
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    return server


def swift_source_path():
    return Path(__file__).resolve().parent / "pet_mac.swift"


def ensure_mac_binary(force_build=False):
    """macOS 네이티브 오버레이 바이너리를 컴파일(캐시)하고 경로를 반환한다.

    앱 번들(.app)은 미리 컴파일한 바이너리를 RO_PET_HOST로 알려 준다. 그러면 swiftc 없이도 실행된다.
    """
    prebuilt = os.environ.get("RO_PET_HOST")
    if prebuilt and not force_build and os.access(prebuilt, os.X_OK):
        return Path(prebuilt)
    src = swift_source_path()
    if not src.exists() or not shutil.which("swiftc"):
        return None
    cache_dir = Path(tempfile.gettempdir()) / f"ro-pet-{os.getuid()}"
    fsutil.ensure_dir(cache_dir)
    bin_path = cache_dir / "ro-pet-host"
    if not force_build and bin_path.exists() and bin_path.stat().st_mtime >= src.stat().st_mtime:
        return bin_path
    cmd = ["swiftc", "-O", str(src), "-o", str(bin_path), "-framework", "AppKit", "-framework", "WebKit", "-framework", "Carbon",
           "-framework", "IOKit", "-framework", "CoreAudio", "-framework", "AVFoundation"]
    r = subprocess.run(cmd, capture_output=True, text=True, timeout=60)
    if r.returncode != 0:
        raise RuntimeError(f"macOS 펫 오버레이 컴파일 실패:\n{r.stderr}")
    os.chmod(bin_path, 0o700)
    return bin_path


def _is_pet_process(pid, key):
    """PID가 재사용됐을 수 있으니 명령줄이 실제 ro pet / ro-pet-host일 때만 참."""
    r = subprocess.run(["ps", "-p", str(pid), "-o", "command="], capture_output=True, text=True, timeout=5)
    cmd = r.stdout.strip()
    if key == "host_pid":
        return "ro-pet-host" in cmd
    args = [Path(a).name for a in cmd.split()]
    return "ro" in args and "pet" in args  # `ro pet …` 또는 `python -m ro pet …`


def stop_existing_pets(home=config.HOME):
    """이미 실행 중인 이전 ro pet / ro-pet-host 프로세스를 모두 정리해 중복 실행(2마리 현상)을 막는다."""
    pid_file = Path(home).expanduser() / "pet.pid"
    my_pid = os.getpid()
    if pid_file.exists():
        try:
            info = json.loads(pid_file.read_text(encoding="utf-8"))
            for key in ("host_pid", "py_pid"):
                old_pid = info.get(key)
                if (isinstance(old_pid, int) and old_pid > 1 and old_pid != my_pid
                        and _is_pet_process(old_pid, key)):
                    try:
                        os.kill(old_pid, signal.SIGTERM)
                    except OSError:
                        pass
        except Exception:
            pass
    if sys.platform == "darwin":
        try:
            subprocess.run(["pkill", "-f", "ro-pet-host"], capture_output=True, timeout=5)
        except subprocess.TimeoutExpired:
            pass


def _write_pid_file(home, host_pid=None):
    pid_file = Path(home).expanduser() / "pet.pid"
    fsutil.atomic_write(pid_file, json.dumps({"py_pid": os.getpid(), "host_pid": host_pid}))


def _read_host(runtime, stream):
    for line in stream:
        try:
            runtime.on_host_line(line)
        except Exception:   # 센서 한 줄 때문에 펫이 멈추지 않는다
            continue


def launch(port=0, mode="overlay", wander=True, build_only=False):
    """macOS 데스크톱 오버레이+메뉴바 펫(기본) 또는 브라우저 모드로 실행한다."""
    if build_only:
        path = ensure_mac_binary(force_build=True)
        return str(path) if path else None

    stop_existing_pets()
    runtime = PetRuntime()
    server = start_server(runtime, "127.0.0.1", port)
    activity.Recorder().start()   # 켜져 있을 때만 남긴다(ro activity on). 꺼져 있으면 아무것도 하지 않는다
    actual_port = server.server_address[1]
    url = f"http://127.0.0.1:{actual_port}/"
    log.append("pet", "펫 시작", {"port": actual_port, "mode": mode}, log_dir=runtime.log_dir)
    child_proc = None
    restart = False

    def _cleanup(*_args):
        if child_proc and child_proc.poll() is None:
            try:
                child_proc.terminate()
            except OSError:
                pass

    atexit.register(_cleanup)
    for sig in (signal.SIGINT, signal.SIGTERM):
        try:
            signal.signal(sig, lambda s, f: (_cleanup(), sys.exit(0)))
        except ValueError:
            pass

    try:
        if mode == "overlay" and sys.platform == "darwin":
            bin_path = ensure_mac_binary()
            if bin_path:
                print(f"ro pet running (desktop overlay + menu bar): {url}  [quit: Ctrl+C or the menu bar icon]")
                cmd = [str(bin_path), "--url", url]
                if wander:
                    cmd.append("--wander")
                if runtime.edition == "mini":
                    cmd.append("--mini")
                    child_proc = subprocess.Popen(cmd)
                else:  # pro: 센서는 stdout으로 오고 토스트 명령은 stdin으로 간다(네트워크 없음)
                    cmd.append("--pro")
                    child_proc = subprocess.Popen(cmd, stdin=subprocess.PIPE, stdout=subprocess.PIPE,
                                                  text=True, bufsize=1, encoding="utf-8")
                    runtime.attach_host(child_proc.stdin)
                    from . import prowatch
                    threading.Thread(target=prowatch.run_forever, args=(runtime.pro, threading.Event()),
                                     daemon=True, name="ro-pro-watch").start()
                    threading.Thread(target=_read_host, args=(runtime, child_proc.stdout),
                                     daemon=True, name="ro-host-pipe").start()
                _write_pid_file(runtime.home, child_proc.pid)
                runtime.on_force_restart = child_proc.terminate
                threading.Thread(target=_license_watch, args=(runtime,), daemon=True, name="ro-license-watch").start()
                # 키로 에디션이 바뀌었고 호스트가 '지금 다시 시작'으로 끝났을 때, 또는 자동으로 받은 키로 pro가 됐을 때 다시 연다
                restart = (child_proc.wait() == RESTART_EXIT and runtime.restart_requested) or runtime.force_restart
                return url
        _write_pid_file(runtime.home, None)
        import webbrowser
        print(f"ro pet running (browser): {url}  [quit: Ctrl+C]")
        webbrowser.open(url)
        while True:
            time.sleep(1)
    except KeyboardInterrupt:
        print("\nQuitting ro pet.")
    finally:
        _cleanup()
        server.shutdown()
        server.server_close()
        if restart:
            _restart_self(runtime.log_dir)
    return url


def _license_watch(runtime):
    """자동 받기: 구매 대기 중엔 15초마다, pro면 하루 한 번(licensenet.due가 정한다). 그 밖엔 연락하지 않는다."""
    while True:
        try:
            runtime.license_tick()
        except Exception:   # 연락 실패가 펫을 멈추지 않는다
            pass
        time.sleep(licensenet.PENDING_EVERY)


def _restart_self(log_dir=log.LOG_DIR):
    """같은 인터프리터·인자로 자신을 다시 실행한다. ro/__main__.py가 키를 다시 읽어 에디션을 정한다."""
    log.append("pet", "라이선스 변경으로 다시 시작", {}, log_dir=log_dir)
    sys.stdout.flush()
    sys.stderr.flush()
    os.execv(sys.executable, [sys.executable, "-m", "ro", *sys.argv[1:]])
