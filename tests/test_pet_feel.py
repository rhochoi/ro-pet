"""표정과 모션의 '느낌' 회귀 검사. 실제 펫 창 크기(176×168)에서 프레임을 재서 본다."""
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

RECORD = """(ms) => new Promise(done => {
  const frames = [], start = performance.now();
  const box = el => { const r = el.getBoundingClientRect(); return {x: r.x, y: r.y, w: r.width, h: r.height}; };
  (function tick() {
    frames.push({t: performance.now() - start, h: box(layerHead), b: box(layerBody), s: box(layerBase), act: currentAction});
    performance.now() - start < ms ? requestAnimationFrame(tick) : done(frames);
  })();
})"""


def spread(frames, layer, axis="y"):
    values = [f[layer][axis] for f in frames]
    return max(values) - min(values)


def biggest_step(frames):
    """한 프레임(16.7ms)당 가장 크게 움직인 거리. 콜백이 붙어 와도(느린 CI) 한 프레임보다 짧은 간격으로 나눠 부풀리지 않는다."""
    return max(abs(a[k][c] - b[k][c]) * 16.7 / max(b["t"] - a["t"], 16.7)
               for a, b in zip(frames, frames[1:]) for k in "hbs" for c in "xy")


def head_gap(frames):
    return min(f["b"]["y"] - (f["h"]["y"] + f["h"]["h"]) for f in frames)


@unittest.skipUnless(sync_playwright, "playwright 필요")
class FeelTest(unittest.TestCase):
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

    def setUp(self):
        ctx = self.browser.new_context(viewport={"width": 176, "height": 168})
        self.addCleanup(ctx.close)
        self.page = ctx.new_page()
        self.page.goto("http://127.0.0.1:%d/" % self.server.server_address[1])
        self.page.wait_for_function("typeof window.triggerAction === 'function'")
        self.page.wait_for_timeout(300)

    def act(self, name, ms):
        self.page.evaluate("name => window.triggerAction(name)", name)
        return self.page.evaluate(RECORD, ms)

    def test_petting_presses_the_head_down_and_lets_it_recover(self):
        rest = self.page.evaluate(RECORD, 700)
        frames = self.act("pet", 900)
        # 눌림이 자리 잡은 뒤(60fps 기준 약 20프레임)만 본다. 느린 CI는 프레임이 적게 오므로 개수가 아니라 경과 시간으로 고른다.
        pressed = [f for f in frames if f["t"] >= 330]
        self.assertTrue(rest and pressed, "프레임 부족: 쉬는 %d개, 쓰다듬기 %d개 중 330ms 이후 %d개"
                        % (len(rest), len(frames), len(pressed)))
        self.assertGreater(sum(f["h"]["y"] for f in pressed) / len(pressed),
                           sum(f["h"]["y"] for f in rest) / len(rest) + 2.5)
        self.assertGreater(head_gap(pressed), 0)
        self.page.evaluate("window.triggerAction(null)")
        self.assertLess(biggest_step(self.page.evaluate(RECORD, 500)), 3.5)

    def test_breathe_is_deeper_than_resting(self):
        rest = self.page.evaluate(RECORD, 3100)
        deep = self.act("breathe", 3100)
        self.assertGreater(spread(deep, "h"), spread(rest, "h") * 1.5)

    def test_every_mood_keeps_breathing_after_it_settles(self):
        for mood in ("recording", "focus", "anxious", "discovery", "resolved"):
            with self.subTest(mood=mood):
                self.page.evaluate("m => window.setMoodPreview(m, 8000)", mood)
                self.page.wait_for_timeout(500)
                self.assertGreater(spread(self.page.evaluate(RECORD, 2600), "h"), 0.8)

    def test_moods_breathe_at_their_own_pace(self):
        pace = {}
        for mood in ("recording", "focus", "anxious", "idle"):
            self.page.evaluate("m => window.setMoodPreview(m, 8000)", mood)
            pace[mood] = self.page.evaluate("getComputedStyle(layerHead).animationDuration")
        self.assertEqual(len(set(pace.values())), 4, pace)

    def test_sleeping_head_rests_on_the_body_without_sinking_in(self):
        frames = self.act("drowsy", 900)
        self.assertGreaterEqual(head_gap(frames), 0)
        self.page.evaluate("window.triggerAction(null)")
        self.assertLess(biggest_step(self.page.evaluate(RECORD, 500)), 3.5)

    def test_loops_end_on_a_full_cycle(self):
        ms = self.page.evaluate("ACTION_MS")
        for name, cycle in (("breathe", 3000), ("look_around", 3000), ("walk", 390), ("thinking", 1600)):
            self.assertEqual(ms[name] % cycle, 0, name)

    def test_one_shots_do_not_stay_frozen(self):
        for name in ("alert", "success", "failure"):
            with self.subTest(action=name):
                ended = [f["t"] for f in self.act(name, 2300) if f["act"] != name]
                self.assertTrue(ended and ended[0] < 2000, name)

    def test_jumps_have_no_velocity_pop(self):
        for name, limit in (("alert", 7), ("success", 7)):
            with self.subTest(action=name):
                frames = self.act(name, 1000)
                self.assertLess(biggest_step(frames), limit)
                self.assertGreater(spread(frames, "h"), 10)

    def test_success_crouches_before_it_jumps(self):
        frames = self.act("success", 300)
        start = frames[0]["s"]["h"]
        self.assertLess(min(f["s"]["h"] for f in frames), start - 1)

    def test_failure_lets_the_layers_slip(self):
        before = self.page.evaluate("layerBody.getBoundingClientRect().x - layerHead.getBoundingClientRect().x")
        self.act("failure", 900)
        after = self.page.evaluate("layerBody.getBoundingClientRect().x - layerHead.getBoundingClientRect().x")
        self.assertGreater(abs(after - before), 4)

    def test_head_follows_the_cursor_on_top_of_breathing(self):
        self.page.evaluate("followPointer(170, 60)")
        self.page.wait_for_timeout(350)
        self.assertNotEqual(self.page.evaluate("layerHead.style.getPropertyValue('--look-x')"), "")
        self.assertEqual(self.page.evaluate("getComputedStyle(layerHead).animationName"), "breatheHead")
        self.assertNotEqual(self.page.evaluate("getComputedStyle(layerHead).translate"), "none")

    def test_a_new_chip_interrupts_a_running_demo(self):
        self.page.evaluate("window.triggerAction('shake')")
        self.page.wait_for_timeout(500)
        self.page.evaluate("window.triggerAction('press')")
        self.page.wait_for_function("!RoMotion.busy() && currentAction === null", timeout=3000)
        self.assertEqual(self.page.evaluate("document.getElementById('petWrap').dataset.eyes || ''"), "")

    def test_eyes_ease_back_after_a_smile(self):
        self.assertIn("eyeIn", pet.PET_HTML)
        self.assertIn("archIn", pet.PET_HTML)


if __name__ == "__main__":
    unittest.main()
