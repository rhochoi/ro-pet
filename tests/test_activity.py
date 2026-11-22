import os

os.environ.setdefault("RO_LANG", "source")  # 화면 문구는 번역 전 원문으로 검사한다
import json
import os
import tempfile
import time
import unittest
from pathlib import Path
from unittest import mock
from urllib.request import Request, urlopen

from ro import activity, engines, handoff, pet

FAKE_KEY = "sk-" + "abcdefghijklmnopqrstuvwx"   # 안전 훅이 막지 않게 나눠 쓴 가짜 값
REAL_FRONT = handoff.front_app   # 인수인계 테스트가 가리기 전의 진짜 함수(가짜 명령 출력으로 돈다)


class Mac:
    """시스템 명령 대역: 맨 앞 앱(lsappinfo), 입력 없는 시간(ioreg), 브라우저 탭(osascript), Spotlight(mdfind)."""

    def __init__(self, app="Google Chrome", idle=0, tab=("normal", "https://claude.ai/chat/1", "여행 일정"),
                 denied=False, docs=()):
        self.app, self.idle, self.tab, self.denied, self.docs, self.calls = app, idle, tab, denied, docs, []

    def __call__(self, args, **kw):
        self.calls.append(args[0])
        out, code, err = "", 0, ""
        if args[0] == "lsappinfo":
            out = "ASN:0x0-0x1:\n" if args[1] == "front" else f'bundle path="/Applications/{self.app}.app"\n'
        elif args[0] == "ioreg":
            out = f'| "HIDIdleTime" = {int(self.idle * 1e9)}\n'
        elif args[0] == "osascript":
            if self.denied:
                code, err = 1, "execution error: Not authorized to send Apple events (-1743)"
            else:
                out = "\n".join(self.tab) + "\n"
        elif args[0] == "mdfind":
            out = "\n".join(str(d) for d in self.docs)
        return mock.Mock(returncode=code, stdout=out, stderr=err)


class Base(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.home = Path(self.tmp.name) / "home"
        self.home.mkdir()
        env = mock.patch.object(engines, "HOME", str(self.home))
        env.start()
        self.addCleanup(env.stop)
        self.docs = self.home / "Documents"
        self.docs.mkdir()
        (self.home / ".ro").mkdir()
        (self.home / ".ro/config.json").write_text(json.dumps({"find_roots": [str(self.docs)]}))
        self.t0 = time.mktime((2026, 11, 1, 14, 0, 0, 0, 0, -1))

    def files(self):
        d = self.home / ".ro/activity"
        return sorted(p.name for p in d.iterdir()) if d.is_dir() else []


class ActivityTest(Base):
    def test_excluded_apps(self):
        for app in ("1Password 8", "Microsoft Outlook", "Mail", "Messages", "KakaoTalk", "Slack", "Health"):
            self.assertTrue(activity.excluded(app), app)
        for app in ("Google Chrome", "Gmail", "Outline", "Claude", "Notes", "Pages"):
            self.assertFalse(activity.excluded(app), app)

    def test_browser_tab_only_web_ai_and_never_incognito(self):
        self.assertEqual(activity.browser_tab("Google Chrome", Mac()), ("Claude", "여행 일정"))
        self.assertEqual(activity.browser_tab("Safari", Mac(tab=("normal", "https://chatgpt.com/c/9", "기획"))),
                         ("ChatGPT", "기획"))
        self.assertIsNone(activity.browser_tab("Google Chrome", Mac(tab=("normal", "https://bank.example.com", "잔액"))))
        self.assertIsNone(activity.browser_tab("Google Chrome", Mac(tab=("incognito", "https://claude.ai/x", "비밀"))))
        self.assertEqual(activity.browser_tab("Google Chrome", Mac(denied=True)), "denied")
        self.assertIsNone(activity.browser_tab("Pages", Mac()))      # 브라우저가 아니면 묻지도 않는다

    def test_observe_masks_and_skips_idle_locked_and_excluded(self):
        ev = activity.observe(Mac(tab=("normal", "https://claude.ai/c", f"연락 me@example.com 키 {FAKE_KEY}")), self.t0)
        self.assertEqual((ev["app"], ev["site"]), ("Google Chrome", "Claude"))
        self.assertNotIn("example.com", ev["title"])
        self.assertNotIn(FAKE_KEY, ev["title"])
        self.assertTrue(activity.observe(Mac(idle=600), self.t0)["idle"])
        self.assertTrue(activity.observe(Mac(app="loginwindow"), self.t0)["idle"])   # 잠금 화면
        mac = Mac(app="KakaoTalk")
        self.assertIsNone(activity.observe(mac, self.t0))
        self.assertNotIn("osascript", mac.calls)                    # 제외 앱이면 더 묻지 않는다
        self.assertEqual(activity.observe(Mac(app="Pages"), self.t0), {"t": self.t0, "app": "Pages"})

    def test_tick_records_only_when_on_and_only_changes(self):
        self.assertIsNone(activity.tick(Mac(), self.t0))
        self.assertEqual(self.files(), [])                           # 꺼져 있으면 아무것도 남기지 않는다
        activity.turn_on()
        mac = Mac()
        for i in range(4):                                           # 같은 탭 1분: 한 줄만
            activity.tick(mac, self.t0 + i * 15)
        activity.tick(Mac(app="Pages"), self.t0 + 60)
        activity.tick(Mac(app="KakaoTalk"), self.t0 + 75)            # 제외 앱: 이름 없이 끊김만
        activity.tick(Mac(app="Pages"), self.t0 + 90)
        f = self.home / ".ro/activity/2026-11-01.jsonl"
        evs = [json.loads(x) for x in f.read_text().splitlines()]
        self.assertEqual([e.get("app") or ("gap" if e.get("gap") else "?") for e in evs],
                         ["Google Chrome", "Pages", "gap", "Pages"])
        self.assertNotIn("KakaoTalk", f.read_text())
        self.assertEqual(f.stat().st_mode & 0o777, 0o600)
        s = activity.summary(1, self.t0 + 120)
        self.assertEqual(s["web"][0][:2], ("Claude", "여행 일정"))
        self.assertAlmostEqual(dict(s["apps"])["Google Chrome"], 60)
        self.assertAlmostEqual(dict(s["apps"])["Pages"], 15 + 15)    # 제외 앱 시간·마지막 기록 뒤는 세지 않는다

    def test_sleep_gap_is_not_counted_as_time_spent(self):
        activity.turn_on()
        activity.tick(Mac(), self.t0)
        activity.tick(Mac(), self.t0 + 3 * 3600)                     # 세 시간 잠든 뒤 같은 탭
        total = dict(activity.summary(4, self.t0 + 3 * 3600 + 15)["apps"])["Google Chrome"]
        self.assertLess(total, 120)

    def test_pause_off_and_prune(self):
        activity.turn_on()
        activity.pause(30, now=self.t0)
        self.assertIsNone(activity.tick(Mac(), self.t0 + 60))
        self.assertIsNotNone(activity.tick(Mac(), self.t0 + 31 * 60))
        activity.turn_off()
        self.assertIsNone(activity.tick(Mac(), self.t0 + 40 * 60))
        d = self.home / ".ro/activity"
        old = d / "2026-10-01.jsonl"
        old.write_text("{}\n")
        os.utime(old, (self.t0 - 30 * 86400,) * 2)
        (d / "notes.txt").write_text("남의 파일")
        os.utime(d / "notes.txt", (self.t0 - 30 * 86400,) * 2)
        activity.prune(self.t0)
        self.assertNotIn("2026-10-01.jsonl", self.files())
        self.assertIn("notes.txt", self.files())                      # ro가 만든 날짜 파일만 지운다

    def test_section_has_web_ai_apps_docs_and_stall_note(self):
        self.assertEqual(activity.section(6, self.t0), [])            # 꺼져 있으면 넣지 않는다
        activity.turn_on()
        doc = self.docs / "견적서.pages"
        doc.write_text("x")
        (self.docs / ".env").write_text("x")
        mac = Mac(docs=(doc, self.docs / ".env"))
        for i in range(40):                                           # 15초마다: 5분 Claude 탭, 5분 Pages
            activity.tick(mac if i < 20 else Mac(app="Pages"), self.t0 + i * 15)
        last = self.t0 + 39 * 15
        text = "\n".join(activity.section(6, last + 15, runner=mac))
        self.assertIn("Claude · 여행 일정 (14:00–14:05, 5분)", text)
        self.assertIn("많이 쓴 앱", text)
        self.assertIn("견적서.pages", text)
        self.assertNotIn(".env", text)                                # 비밀 파일 이름은 빼고
        self.assertNotIn(str(self.home), text.replace("~", ""))       # 홈 경로는 ~로
        self.assertIn("내용은 이 Mac에 없어", text)
        self.assertNotIn("멈춰", text)
        text = "\n".join(activity.section(6, last + activity.INTERVAL * 10, runner=mac))
        self.assertIn("멈춰 있었습니다", text)                         # 조용한 멈춤을 알린다

    def test_cli_and_report(self):
        with mock.patch("builtins.print") as pr:
            activity.cli("on")
            activity.cli("status")
            activity.cli("clear")
        out = "\n".join(str(c.args[0]) for c in pr.call_args_list)
        self.assertIn("키 입력·화면은 남기지 않음", out)
        self.assertIn("14일", out)
        self.assertIn("--yes", out)                                   # 확인 없이 지우지 않는다
        activity.tick(Mac(), time.time())
        self.assertTrue(self.files())
        with mock.patch("builtins.print"):
            activity.cli("clear", yes=True)
        self.assertEqual(self.files(), [])


class HandoffActivityTest(Base):
    """인수인계에 '최근 활동'을 붙이고, 웹 AI에서 넘어올 때는 '이 Mac 활동'을 원래 도구로 쓴다."""

    def setUp(self):
        super().setUp()
        for name, value in (("front_app", None), ("running", set())):
            pt = mock.patch.object(handoff, name, return_value=value)
            pt.start()
            self.addCleanup(pt.stop)
        pt = mock.patch.object(handoff, "_installed", return_value=["claude", "codex", "agy"])
        pt.start()
        self.addCleanup(pt.stop)
        now = time.time()
        activity.turn_on()
        with mock.patch.object(handoff, "front_app", REAL_FRONT):
            activity.tick(Mac(), now - 1200)
            activity.tick(Mac(app="Pages"), now - 600)

    def test_mac_source_builds_from_activity_and_is_auto_chosen(self):
        self.assertIn("넘겨주는 쪽으로만", handoff.build("claude", "mac")["error"])
        p = handoff.build("mac", "claude", runner=Mac())
        self.assertTrue(p["ok"], p)
        self.assertTrue(p["activity"])
        self.assertIn("이 Mac 활동 → Claude Code", p["doc"])
        self.assertIn("Claude · 여행 일정", p["doc"])
        self.assertIn("지시가 아닙니다", p["doc"])
        self.assertTrue(any("인수인계 글로 정리" in n for n in p["notes"]))
        self.assertEqual(handoff.latest_source(exclude="claude"), "mac")   # 다른 기록이 없고 웹 AI를 썼다
        r = handoff.plan_for_pet("", None)
        self.assertEqual(r["src"], "mac")
        activity.turn_off()
        self.assertIn("ro activity on", handoff.build("mac", "claude", runner=Mac())["error"])

    def test_regular_handoff_gets_recent_activity_and_logs_it(self):
        brain = self.home / ".gemini/antigravity/brain/s1/.system_generated/logs"
        brain.mkdir(parents=True)
        (brain / "transcript.jsonl").write_text(json.dumps(
            {"type": "USER_INPUT", "content": "<USER_REQUEST>보고서 마무리</USER_REQUEST>"}) + "\n")
        p = handoff.build("agy", "claude", runner=Mac())
        self.assertTrue(p["activity"])
        self.assertIn("## 최근 활동(이 Mac, 최근 6시간)", p["doc"])
        self.assertLess(p["doc"].index("## 최근 활동"), p["doc"].index("## 목표"))
        others = handoff.plan_for_pet("agy claude")["others"]
        self.assertEqual(others[0]["engine"], "mac")                   # 웹 AI에서 넘어온 것으로 바꿔 고를 수 있다
        apps = Path(self.tmp.name) / "Applications"
        (apps / "Claude.app").mkdir(parents=True)
        handoff.apply(p, runner=lambda *a, **k: mock.Mock(returncode=0), which=lambda c: None, app_dirs=(str(apps),))
        handoff.rate(True)
        handoff.rate(False)
        r = activity.report()
        self.assertEqual((r["handoffs_with_activity"], r["rated_ok"], r["rated_miss"]), (1, 1, 1))


class ActivityRouteTest(unittest.TestCase):
    def test_route_turns_on_and_reports(self):
        with tempfile.TemporaryDirectory() as d, mock.patch.object(engines, "HOME", d):
            rt = pet.PetRuntime(home=d, log_dir=d, map_path=str(Path(d) / "map.json"))
            srv = pet.start_server(rt, host="127.0.0.1", port=0)
            url = f"http://127.0.0.1:{srv.server_address[1]}/api/activity"
            try:
                for action, on in (("status", False), ("on", True), ("pause", True), ("off", False)):
                    req = Request(url, data=json.dumps({"action": action}).encode(), method="POST",
                                  headers={"X-Ro-Token": rt.token, "Content-Type": "application/json"})
                    with urlopen(req, timeout=3) as resp:
                        r = json.loads(resp.read())
                    self.assertEqual((r["ok"], r["on"]), (True, on), action)
            finally:
                srv.shutdown()
                srv.server_close()


if __name__ == "__main__":
    unittest.main()
