"""쓰다듬기: 머리에 손을 올린 것만으로는 반응하지 않고, 문질러야 반응한다."""
import os

os.environ.setdefault("RO_LANG", "source")  # 화면 문구는 번역 전 원문으로 검사한다
import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path

from ro import pet
from tests._pet_browser import launch_chromium

try:
    from playwright.sync_api import sync_playwright
except ImportError:
    sync_playwright = None


@unittest.skipUnless(shutil.which("node"), "node 필요")
class StrokeDetectorTest(unittest.TestCase):
    def feed(self, moves):
        src = pet.PET_HTML[pet.PET_HTML.index("const STROKE ="):pet.PET_HTML.index("/* 쓰다듬기 연결 */")]
        script = src + f"""
const d = createStrokeDetector();
console.log(JSON.stringify({moves!r}.map(([x, t]) => d.move(x, t))));
"""
        out = subprocess.run(["node", "-e", script], capture_output=True, text=True, timeout=10)
        self.assertEqual(out.returncode, 0, out.stderr)
        return out.stdout.strip()

    def test_resting_and_one_way_pass_do_not_count(self):
        self.assertNotIn("true", self.feed([[50, t * 16] for t in range(40)]))
        self.assertNotIn("true", self.feed([[10 + t * 3, t * 16] for t in range(40)]))

    def test_tiny_jitter_does_not_count(self):
        self.assertNotIn("true", self.feed([[50 + (t % 2) * 3, t * 40] for t in range(40)]))

    def test_rubbing_back_and_forth_counts(self):
        path = [30, 45, 60, 45, 30, 45, 60]
        self.assertTrue(self.feed([[x, i * 60] for i, x in enumerate(path)]).endswith("true]"))

    def test_slow_separate_passes_do_not_add_up(self):
        path = [[30, 0], [60, 100], [30, 1200], [60, 2400], [30, 3600]]
        self.assertNotIn("true", self.feed(path))


@unittest.skipUnless(sync_playwright, "playwright 필요")
class StrokeWebTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tmp = tempfile.TemporaryDirectory()
        cls.addClassCleanup(cls.tmp.cleanup)
        d = cls.tmp.name
        cls.rt = pet.PetRuntime(home=d, log_dir=d, map_path=str(Path(d) / "map.json"))
        cls.server = pet.start_server(cls.rt)
        cls.addClassCleanup(cls.server.server_close)
        cls.addClassCleanup(cls.server.shutdown)
        cls.pw = sync_playwright().start()
        cls.addClassCleanup(cls.pw.stop)
        cls.browser = launch_chromium(cls.pw)
        cls.addClassCleanup(cls.browser.close)

    def setUp(self):
        ctx = self.browser.new_context(viewport={"width": 420, "height": 800})
        self.addCleanup(ctx.close)
        self.page = ctx.new_page()
        self.page.goto("http://127.0.0.1:%d/" % self.server.server_address[1])
        self.page.wait_for_function("typeof window.triggerAction === 'function'")
        box = self.page.locator("#layerHead").bounding_box()
        self.x, self.y, self.w = box["x"], box["y"] + box["height"] / 2, box["width"]

    def test_no_hover_tooltip_on_the_pet(self):
        self.assertIsNone(self.page.locator("#petWrap").get_attribute("title"))
        self.assertIsNone(self.page.locator("#bubbleTop").get_attribute("title"))
        self.assertIn("ro", self.page.locator("#petWrap").get_attribute("aria-label"))

    def test_file_drop_caption_is_visible(self):
        self.page.evaluate("setDropActive(true)")
        self.page.wait_for_timeout(300)
        self.assertGreater(float(self.page.evaluate("getComputedStyle(petCaption).opacity")), 0.5)

    def test_caption_does_not_appear_on_hover(self):
        self.page.mouse.move(self.x + self.w / 2, self.y)
        self.page.wait_for_timeout(300)
        self.assertEqual(self.page.evaluate("getComputedStyle(petCaption).opacity"), "0")

    def test_resting_hand_gets_no_reaction(self):
        self.page.mouse.move(self.x + self.w / 2, self.y)
        self.page.wait_for_timeout(500)
        self.assertNotEqual(self.page.evaluate("currentAction"), "pet")

    def test_rubbing_reacts_and_stopping_ends_it(self):
        lo, hi = self.x + self.w * 0.3, self.x + self.w * 0.7
        for _ in range(3):
            self.page.mouse.move(lo, self.y, steps=4)
            self.page.mouse.move(hi, self.y, steps=4)
        self.assertEqual(self.page.evaluate("currentAction"), "pet")
        self.page.wait_for_function("currentAction !== 'pet'", timeout=2000)

    def test_rubbing_the_base_is_not_petting(self):
        box = self.page.locator("#layerBase").bounding_box()
        y = box["y"] + box["height"] / 2
        for _ in range(3):
            self.page.mouse.move(box["x"] + 20, y, steps=4)
            self.page.mouse.move(box["x"] + 70, y, steps=4)
        self.assertNotEqual(self.page.evaluate("currentAction"), "pet")


@unittest.skipUnless(sync_playwright, "playwright 필요")
class HostPointerTest(unittest.TestCase):
    """활성 창이 아니면 웹 화면에 마우스 이동이 오지 않아, 네이티브 호스트가 좌표를 넘겨준다."""

    @classmethod
    def setUpClass(cls):
        cls.tmp = tempfile.TemporaryDirectory()
        cls.addClassCleanup(cls.tmp.cleanup)
        d = cls.tmp.name
        cls.rt = pet.PetRuntime(home=d, log_dir=d, map_path=str(Path(d) / "map.json"))
        cls.server = pet.start_server(cls.rt)
        cls.addClassCleanup(cls.server.server_close)
        cls.addClassCleanup(cls.server.shutdown)
        cls.pw = sync_playwright().start()
        cls.addClassCleanup(cls.pw.stop)
        cls.browser = launch_chromium(cls.pw)
        cls.addClassCleanup(cls.browser.close)

    def setUp(self):
        ctx = self.browser.new_context(viewport={"width": 420, "height": 800})
        self.addCleanup(ctx.close)
        ctx.add_init_script("window.webkit = {messageHandlers: {roHost: {postMessage: () => {}}}};")
        self.page = ctx.new_page()
        self.page.goto("http://127.0.0.1:%d/" % self.server.server_address[1])
        self.page.wait_for_function("typeof window.onHostPointer === 'function'")
        box = self.page.locator("#layerHead").bounding_box()
        self.x, self.y, self.w = box["x"], box["y"] + box["height"] / 2, box["width"]

    def send(self, xs):
        for x in xs:
            self.page.evaluate("([x, y]) => window.onHostPointer(x, y)", [x, self.y])
            self.page.wait_for_timeout(30)

    def rub(self):
        lo, hi = self.x + self.w * 0.3, self.x + self.w * 0.7
        self.send([lo, hi, lo, hi, lo, hi])

    def test_host_pointer_rubbing_reacts(self):
        self.rub()
        self.assertEqual(self.page.evaluate("currentAction"), "pet")
        self.page.wait_for_function("currentAction !== 'pet'", timeout=2000)

    def test_host_pointer_resting_does_not_react(self):
        self.send([self.x + 40] * 8)
        self.assertNotEqual(self.page.evaluate("currentAction"), "pet")

    def test_leaving_the_window_ends_petting(self):
        self.rub()
        self.page.evaluate("window.onHostPointer(null)")
        self.assertNotEqual(self.page.evaluate("currentAction"), "pet")

    def test_host_pointer_counts_as_activity_and_moves_gaze(self):
        self.page.evaluate("lastUserActivity = 0")
        self.send([self.x + self.w + 40])
        self.assertGreater(self.page.evaluate("lastUserActivity"), 0)
        self.assertIn("translate", self.page.evaluate("eyesWrap.style.transform"))

    def test_swift_host_takes_the_first_click_while_inactive(self):
        src = (Path(pet.__file__).parent / "pet_mac.swift").read_text(encoding="utf-8")
        self.assertIn("override func acceptsFirstMouse(for event: NSEvent?) -> Bool { true }", src)
        self.assertIn("webView = PetWebView(frame:", src)

    def test_swift_host_returns_the_pet_after_a_pushed_panel(self):
        src = (Path(pet.__file__).parent / "pet_mac.swift").read_text(encoding="utf-8")
        self.assertIn("clampOrigin(originBeforeOpen ?? petPos, size: compactSize)", src)
        self.assertIn("self.originBeforeOpen = nil  // 직접 옮겼다면", src)

    def test_swift_host_watches_the_cursor_while_inactive(self):
        src = (Path(pet.__file__).parent / "pet_mac.swift").read_text(encoding="utf-8")
        self.assertIn("addGlobalMonitorForEvents(matching: [.mouseMoved, .leftMouseDragged]", src)
        self.assertIn("addLocalMonitorForEvents(matching: .mouseMoved", src)
        self.assertIn("window.onHostPointer", src)


if __name__ == "__main__":
    unittest.main()
