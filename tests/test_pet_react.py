"""앱 반응(open·mail·message) 회귀 검사. 문자열만 보지 않고 선점 규칙을 실제 페이지에서 돌려 본다."""
import os

os.environ.setdefault("RO_LANG", "source")  # 화면 문구는 번역 전 원문으로 검사한다
import tempfile
import unittest
from pathlib import Path

from ro import pet
from tests._pet_browser import launch_chromium

try:
    from playwright.sync_api import sync_playwright
except ImportError:
    sync_playwright = None

HOST = "window.hostMessages = []; window.webkit = {messageHandlers: {roHost: {postMessage: m => hostMessages.push(m)}}};"
STATE = "({react: petWrap.getAttribute('data-react'), action: currentAction, drowsy: isDrowsy, busy: RoMotion.busy(), cls: petWrap.className})"


class ReactSourceTest(unittest.TestCase):
    def setUp(self):
        self.swift = (Path(pet.__file__).parent / "pet_mac.swift").read_text(encoding="utf-8")
        self.react = self.swift.split("// MARK: 앱 반응")[1].split("@objc private func selectSize")[0]

    def test_reactions_are_not_motion_guide_actions(self):
        meta = pet.PET_HTML.split("const ACTION_META = {")[1].split("\n};")[0]
        for kind in ("open", "mail", "message"):
            self.assertNotIn(kind, pet.ACTIONS)
            self.assertNotIn(kind, pet.ACTION_DESCS)
            self.assertNotIn(f"\n  {kind}:", meta)

    def test_bundle_ids_keep_verified_and_unverified_apart(self):
        verified = self.swift.split("let reactMailAppsVerified")[1].split("// 미확인")[0]
        unverified = self.swift.split("// 미확인")[1].split("func reactKind")[0]
        for bundle in ("com.apple.mail", "com.apple.MobileSMS", "com.tinyspeck.slackmacgap", "com.kakao.KakaoTalkMac",
                       "com.hnc.Discord", "com.tdesktop.Telegram"):
            self.assertIn(f'"{bundle}"', verified)
        for bundle in ("com.microsoft.Outlook", "com.readdle.smartemail-Mac", "ru.keepcoder.Telegram",
                       "net.whatsapp.WhatsApp", "jp.naver.line.mac", "com.microsoft.teams2"):
            self.assertIn(f'"{bundle}"', unverified)
            self.assertNotIn(f'"{bundle}"', verified)
        self.assertNotIn('"com.google.Chrome.app.gmail"', verified + unverified)  # 존재하지 않는 ID

    def test_cooldown_is_spent_only_when_the_page_showed_the_reaction(self):
        request = self.react.split("private func requestReaction")[1].split("\n    }\n")[0]
        before, handler = request.split("webView.evaluateJavaScript", 1)
        self.assertIn("reactGate.allows(kind", before)
        self.assertNotIn("succeeded", before)
        self.assertIn("(result as? Bool) == true", handler)
        self.assertIn("reactGate.succeeded(kind", handler)

    def test_host_filters_before_asking_the_page(self):
        request = self.react.split("private func requestReaction")[1].split("\n    }\n")[0]
        # 실제 반응은 데스크톱 모드에서만. 메뉴의 미리보기만 메뉴 막대 모드에서도 잠깐 꺼내 보여 준다
        self.assertIn("guard preview || mode == .desktop, panel?.isVisible == true, !bubbleOpen, !isDragging else { return }", request)
        self.assertIn("reactEnabled, reactKinds.contains(kind)", request)
        self.assertIn("processIdentifier != me", self.react)                      # 펫 자신은 무시
        self.assertIn("activationPolicy == .regular", self.react)
        for key in ('"ro.react.enabled"', '"ro.react.\\(kind.rawValue)"'):
            self.assertIn(key, self.swift)

    def test_only_the_bundle_id_is_read_and_nothing_is_kept(self):
        self.assertNotIn("kCGWindowName", self.swift)       # 창 제목은 읽지 않는다
        self.assertNotIn("localizedName", self.react)       # 앱 이름도 쓰지 않는다
        for leak in ("print(", "NSLog", "os_log", "defaults.set(app", "bundleIdentifier, forKey"):
            self.assertNotIn(leak, self.react)
        self.assertEqual(self.react.count("bundleIdentifier"), 2)  # 실행·활성 알림에서 종류 판정에만 쓴다
        self.assertEqual(self.react.count("reactKind(forBundleID: app.bundleIdentifier)"), 2)

    def test_preview_menu_and_switches_exist(self):
        self.assertIn('menuSection(L("Reactions"))', self.swift)
        self.assertIn("#selector(previewReaction(_:))", self.swift)
        self.assertIn("requestReaction(kind, preview: true)", self.swift)
        self.assertIn("#selector(toggleReactionKind(_:))", self.swift)
        self.assertIn('} else if type == "react" {', self.swift)
        self.assertIn("window.setReactState && window.setReactState(\\(reactEnabled))", self.swift)


@unittest.skipUnless(sync_playwright, "playwright 필요")
class ReactBehaviorTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tmp = tempfile.TemporaryDirectory()
        cls.addClassCleanup(cls.tmp.cleanup)
        d = cls.tmp.name
        cls.rt = pet.PetRuntime(home=d, log_dir=d, map_path=str(Path(d) / "map.json"), edition="mini")
        cls.server = pet.start_server(cls.rt)
        cls.addClassCleanup(cls.server.server_close)
        cls.addClassCleanup(cls.server.shutdown)
        cls.pw = sync_playwright().start()
        cls.addClassCleanup(cls.pw.stop)
        cls.browser = launch_chromium(cls.pw)
        cls.addClassCleanup(cls.browser.close)

    def page(self, viewport=None, **ctx_args):
        ctx = self.browser.new_context(viewport=viewport or {"width": 176, "height": 168}, **ctx_args)
        self.addCleanup(ctx.close)
        ctx.add_init_script(HOST)  # 네이티브 호스트 안에서처럼
        pg = ctx.new_page()
        pg.goto("http://127.0.0.1:%d/" % self.server.server_address[1])
        pg.wait_for_function("typeof window.petReact === 'function'")
        pg.wait_for_timeout(300)
        return pg

    def state(self, pg):
        return pg.evaluate(STATE)

    # ① 졸고 있던 펫도 반응하고 깨어난다 (시제품에서는 여기서 조용히 사라졌다)
    def test_drowsy_pet_reacts_to_mail_and_wakes_up(self):
        pg = self.page()
        pg.evaluate("isDrowsy = true; lastUserActivity = Date.now() - 80000; window.triggerAction('drowsy', 0)")
        self.assertEqual(self.state(pg)["action"], "drowsy")
        self.assertIs(pg.evaluate("window.petReact('mail')"), True)
        st = self.state(pg)
        self.assertEqual(st["react"], "mail")
        self.assertFalse(st["drowsy"])
        self.assertIsNone(st["action"])
        self.assertNotIn("action-drowsy", st["cls"])
        self.assertEqual(pg.evaluate("getComputedStyle(roBot).animationName"), "reactMail")
        pg.wait_for_timeout(4300)  # 졸음 검사 주기(4초)를 지나도 다시 졸지 않고 일반 대기로 돌아온다
        st = self.state(pg)
        self.assertIsNone(st["react"])
        self.assertFalse(st["drowsy"])
        self.assertNotEqual(st["action"], "drowsy")

    # ② 저절로 도는 동작은 반응이 끊고 들어간다
    def test_reaction_cuts_into_idle_actions(self):
        for action in ("look_around", "breathe", "walk", "thinking"):
            with self.subTest(action=action):
                pg = self.page()
                pg.evaluate("a => window.triggerAction(a)", action)
                self.assertIs(pg.evaluate("window.petReact('message')"), True)
                st = self.state(pg)
                self.assertEqual((st["react"], st["action"]), ("message", None))
                self.assertNotIn("action-", st["cls"])

    # ③ 사용자가 만든 동작은 지킨다
    def test_user_made_actions_are_protected(self):
        for action in ("pet", "drag", "shake", "press", "drop", "success", "failure"):
            with self.subTest(action=action):
                pg = self.page()
                pg.evaluate("a => window.triggerAction(a)", action)
                before = self.state(pg)
                self.assertIs(pg.evaluate("window.petReact('mail')"), False)
                self.assertEqual(self.state(pg), before)
                self.assertIsNone(before["react"])

    def test_petting_open_panel_and_unknown_kinds_are_refused(self):
        pg = self.page()
        self.assertIs(pg.evaluate("window.petReact('typing')"), False)
        self.assertIs(pg.evaluate("window.petReact('constructor')"), False)
        pg.evaluate("isPetHover = true")
        self.assertIs(pg.evaluate("window.petReact('mail')"), False)
        pg.evaluate("isPetHover = false; RoMotion.down(performance.now())")  # 누르는 중
        self.assertIs(pg.evaluate("window.petReact('mail')"), False)
        pg.evaluate("RoMotion.reset(); RoMotion.clearStyles(); window.toggleBubbleFromHost(true)")
        self.assertIs(pg.evaluate("window.petReact('mail')"), False)
        self.assertIsNone(self.state(pg)["react"])

    def test_non_idle_expression_still_reacts_and_keeps_its_class(self):
        pg = self.page()
        pg.evaluate("window.setMoodPreview('focus', 10000)")
        moods = pg.evaluate("[...petWrap.classList].filter(c => c.startsWith('mood-'))")
        self.assertIs(pg.evaluate("window.petReact('message')"), True)
        self.assertEqual(pg.evaluate("[...petWrap.classList].filter(c => c.startsWith('mood-'))"), moods)

    # ④ 반응 도중 동작이 시작되면 반응이 물러난다
    def test_an_action_starting_mid_reaction_takes_over(self):
        pg = self.page()
        self.assertIs(pg.evaluate("window.petReact('mail')"), True)
        pg.wait_for_timeout(200)
        pg.evaluate("window.triggerAction('alert')")
        st = self.state(pg)
        self.assertIsNone(st["react"])
        self.assertEqual(st["action"], "alert")
        self.assertEqual(pg.evaluate("getComputedStyle(roBot).animationName"), "alertJump")
        pg.wait_for_timeout(2700)  # 물러난 반응의 타이머가 뒤늦게 무언가를 건드리지 않는다
        self.assertIsNone(self.state(pg)["react"])

    # ⑤ 뱃지는 2.6초 뒤 사라진다
    def test_reaction_clears_itself_after_its_time(self):
        pg = self.page()
        pg.evaluate("window.petReact('mail')")
        pg.wait_for_timeout(600)
        self.assertEqual(pg.evaluate("getComputedStyle(reactBadge).opacity"), "1")
        self.assertTrue(pg.evaluate("!!reactBadge.querySelector('svg')"))
        pg.wait_for_timeout(1750)  # 2.35s
        self.assertEqual(self.state(pg)["react"], "mail")
        pg.wait_for_timeout(450)   # 2.8s
        self.assertIsNone(self.state(pg)["react"])
        pg.wait_for_timeout(300)
        self.assertEqual(pg.evaluate("getComputedStyle(reactBadge).opacity"), "0")

    def test_open_hops_without_a_badge_and_ends_sooner(self):
        pg = self.page()
        self.assertIs(pg.evaluate("window.petReact('open')"), True)
        self.assertEqual(pg.evaluate("getComputedStyle(roBot).animationName"), "reactOpen")
        pg.wait_for_timeout(300)
        self.assertEqual(pg.evaluate("getComputedStyle(reactBadge).opacity"), "0")
        self.assertGreater(pg.evaluate("eyeL.getBoundingClientRect().width"), 2.2 * 3.8)  # 눈이 커진다
        pg.wait_for_timeout(800)
        self.assertIsNone(self.state(pg)["react"])

    # ⑥ 같은 반응이 다시 오면 처음부터 재생한다
    def test_same_reaction_again_restarts_from_the_beginning(self):
        pg = self.page()
        now = "roBot.getAnimations().find(a => a.animationName === 'reactMessage').currentTime"
        pg.evaluate("window.petReact('message')")
        pg.wait_for_timeout(700)
        self.assertGreater(pg.evaluate(now), 500)
        self.assertIs(pg.evaluate("window.petReact('message')"), True)
        self.assertLess(pg.evaluate(now), 200)
        pg.wait_for_timeout(2300)  # 처음 호출 기준으로는 3초: 타이머도 새로 잰다
        self.assertEqual(self.state(pg)["react"], "message")

    # ⑦ 모션 줄이기: 움직임 없이 뱃지만
    def test_reduced_motion_shows_only_the_badge(self):
        pg = self.page(reduced_motion="reduce")
        for kind in ("open", "mail", "message"):
            with self.subTest(kind=kind):
                self.assertIs(pg.evaluate("k => window.petReact(k)", kind), True)
                self.assertEqual(pg.evaluate("getComputedStyle(roBot).animationName"), "none")
                self.assertEqual(pg.evaluate("getComputedStyle(layerHead).getPropertyValue('--sx').trim()"), "0px" if kind == "message" else "")
                if kind != "open":
                    self.assertEqual(pg.evaluate("getComputedStyle(reactBadge).opacity"), "1")
        self.assertEqual(pg.evaluate("getComputedStyle(reactBadge.querySelector('.dot')).animationName"), "none")

    def test_reaction_stays_inside_the_window_at_every_size(self):
        for name, k in (("small", 0.75), ("medium", 1.0), ("big", 1.3)):
            pg = self.page({"width": round(176 * k), "height": round(168 * k)})
            pg.evaluate("n => window.setPetSize(n)", name)
            pg.wait_for_timeout(450)
            for kind in ("open", "mail", "message"):
                with self.subTest(size=name, kind=kind):
                    margin = pg.evaluate("""(kind) => new Promise(done => { let m = 1e9; const start = performance.now();
                      window.petReact(kind);
                      (function tick() {
                        for (const e of [layerHead, layerBody, layerBase].concat(kind === 'open' ? [] : [reactBadge])) {
                          const r = e.getBoundingClientRect();
                          m = Math.min(m, r.left, r.top, innerWidth - r.right, innerHeight - r.bottom);
                        }
                        performance.now() - start < 1500 ? requestAnimationFrame(tick) : (clearReact(), done(m));
                      })(); })""", kind)
                    self.assertGreaterEqual(margin, 0)

    def test_badge_uses_ink_and_cream_not_orange(self):
        pg = self.page()
        pg.evaluate("window.petReact('mail')")
        pg.wait_for_timeout(400)
        style = pg.evaluate("(() => { const s = getComputedStyle(reactBadge); return [s.backgroundColor, s.color]; })()")
        self.assertEqual(style, ["rgb(26, 25, 23)", "rgb(245, 242, 235)"])  # 먹 면 + 크림 글리프

    def test_master_switch_talks_to_the_host(self):
        pg = self.page({"width": 388, "height": 760})
        self.assertTrue(pg.evaluate("reactToggle.checked"))  # 기본은 켬
        pg.evaluate("reactToggle.checked = false; reactToggle.dispatchEvent(new Event('change'))")
        self.assertEqual(pg.evaluate("hostMessages.filter(m => m.type === 'react')"), [{"type": "react", "enabled": False}])
        pg.evaluate("window.setReactState(true)")
        self.assertTrue(pg.evaluate("reactToggle.checked"))


if __name__ == "__main__":
    unittest.main()
