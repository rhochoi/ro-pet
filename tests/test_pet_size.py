"""펫 크기(small/medium/big) 회귀 검사. 세 배율 모두 실제 접힌 창 크기에서 잘림을 잰다."""
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

SIZES = {"small": 0.75, "medium": 1.0, "big": 1.3}
HOST = "window.hostMessages = []; window.webkit = {messageHandlers: {roHost: {postMessage: m => hostMessages.push(m)}}};"

# 동작을 걸고 ms 동안 세 층이 창 가장자리에서 가장 가까웠던 거리(음수면 잘림)를 잰다
MARGIN = """([name, ms]) => new Promise(done => {
  let m = 1e9;
  const start = performance.now();
  window.triggerAction(name);
  (function tick() {
    for (const e of [layerHead, layerBody, layerBase]) {
      const r = e.getBoundingClientRect();
      m = Math.min(m, r.left, r.top, innerWidth - r.right, innerHeight - r.bottom);
    }
    performance.now() - start < ms ? requestAnimationFrame(tick) : (window.triggerAction(null), done(m));
  })();
})"""

# 길게 눌러 잡고 vx,vy(px/s)로 세게 왕복해 흔든 뒤 놓는다(RoMotion을 직접 민다)
SHAKE = """([vx, vy]) => {
  let m = 1e9, t = 1300, x = 0, y = 0;
  const snap = () => {
    RoMotion.advance(t); RoMotion.apply(RoMotion.pose(t));
    for (const e of [layerHead, layerBody, layerBase]) {
      const r = e.getBoundingClientRect();
      m = Math.min(m, r.left, r.top, innerWidth - r.right, innerHeight - r.bottom);
    }
  };
  RoMotion.down(1000); snap();
  for (let k = 0; k < 10; k++) {
    const dir = k % 2 ? -1 : 1;
    for (let e = 0; e < 120; e += 8) { t += 8; x += dir * vx * 0.008; y += dir * vy * 0.008; RoMotion.move(x, y, t); snap(); }
  }
  RoMotion.up(t);
  for (let e = 0; e < 1500; e += 8) { t += 8; snap(); }
  return m;
}"""


def compact(k):
    return {"width": round(176 * k), "height": round(168 * k)}


class SizeSourceTest(unittest.TestCase):
    def setUp(self):
        self.swift = (Path(pet.__file__).parent / "pet_mac.swift").read_text(encoding="utf-8")

    def test_three_sizes_and_medium_is_the_old_window(self):
        self.assertIn('["small": 0.75, "medium": 1.0, "big": 1.3]', self.swift)
        self.assertIn("NSSize(width: 176, height: 168)", self.swift)
        self.assertIn("const PET_SCALES = { small: 0.75, medium: 1, big: 1.3 };", pet.PET_HTML)
        self.assertIn("--u: calc(3.8px * var(--pet-scale, 1));", pet.PET_HTML)
        for name in SIZES:
            self.assertIn(f'data-size="{name}"', pet.PET_HTML)

    def test_host_saves_restores_and_repushes_the_size(self):
        self.assertIn('defaults.set(code, forKey: "ro.size")', self.swift)
        self.assertIn('defaults.string(forKey: "ro.size")', self.swift)
        finish = self.swift.split("didFinish navigation")[1].split("\n    }")[0]
        self.assertIn("window.setPetSize('\\(sizeName)')", finish)  # 페이지를 다시 불러도 medium으로 돌아가지 않는다
        self.assertIn('} else if type == "size" {', self.swift)
        self.assertNotIn(".ro/", self.swift.split("private func applySize")[1].split("\n    }\n")[0])

    def test_resize_while_panel_is_open_drops_the_stale_origin(self):
        body = self.swift.split("private func applySize")[1].split("private func fitPanelToCompactSize")[0]
        open_branch = body.split("if bubbleOpen {")[1].split("}")[0]
        self.assertIn("originBeforeOpen = nil", open_branch)
        self.assertIn("return", open_branch)                                  # 열린 창 프레임은 건드리지 않는다
        self.assertIn("guard mode == .desktop else { return }", body)         # 메뉴 막대 모드도 프레임은 그대로
        fit = self.swift.split("private func fitPanelToCompactSize")[1].split("\n    }\n")[0]
        self.assertIn("petResizeOrigin(frame: panel.frame, newSize: size)", fit)
        self.assertIn("animate: false", fit)
        self.assertIn("refreshGlass()", fit)


@unittest.skipUnless(sync_playwright, "playwright 필요")
class SizeBrowserTest(unittest.TestCase):
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

    def page(self, viewport, host=True, size=None):
        ctx = self.browser.new_context(viewport=viewport)
        self.addCleanup(ctx.close)
        if host:  # 네이티브 호스트 안에서처럼: 창이 곧 펫이다
            ctx.add_init_script(HOST)
        pg = ctx.new_page()
        pg.goto("http://127.0.0.1:%d/" % self.server.server_address[1])
        pg.wait_for_function("typeof window.triggerAction === 'function'")
        if size:
            self.assertTrue(pg.evaluate("n => window.setPetSize(n)", size))
        pg.wait_for_timeout(450)
        return pg

    def test_unit_follows_the_scale_and_medium_keeps_its_pixels(self):
        for name, k in SIZES.items():
            with self.subTest(size=name):
                pg = self.page(compact(k), size=name)
                self.assertAlmostEqual(pg.evaluate("roBot.offsetWidth / 23"), 3.8 * k, delta=0.03)
        pg = self.page(compact(1))  # setPetSize를 부르지 않은 기본값도 medium과 같다
        self.assertAlmostEqual(pg.evaluate("roBot.getBoundingClientRect().width"), 23 * 3.8, delta=0.01)
        self.assertEqual(pg.evaluate("getComputedStyle(petWrap).paddingTop"), "10px")

    def test_actions_stay_inside_the_window_at_every_size(self):
        for name, k in SIZES.items():
            pg = self.page(compact(k), size=name)
            for action in ("success", "alert", "drag", "shake", "drop", "walk", "failure", "drowsy"):
                with self.subTest(size=name, action=action):
                    self.assertGreaterEqual(pg.evaluate(MARGIN, [action, 1100]), 0)

    def test_hard_shaking_stays_inside_the_window_at_every_size(self):
        for name, k in SIZES.items():
            for label, v in (("x", [2400, 0]), ("y", [0, 2400])):
                with self.subTest(size=name, axis=label):
                    pg = self.page(compact(k), size=name)
                    self.assertGreaterEqual(pg.evaluate(SHAKE, v), 0)

    def test_grab_lag_cap_scales_with_the_pet(self):
        lag = {}
        for name, k in SIZES.items():
            pg = self.page(compact(k), size=name)
            lag[name] = pg.evaluate("""() => {
              RoMotion.down(1000); RoMotion.advance(1300);
              for (let e = 0; e <= 1500; e += 8) RoMotion.move(600 * e / 1000, 0, 1300 + e);
              RoMotion.advance(2800);
              return RoMotion.pose(2800).l[2].tx; }""")
        self.assertAlmostEqual(lag["medium"], -12, delta=1.5)  # 기존 한도 그대로
        self.assertAlmostEqual(lag["small"], -9, delta=1.2)
        self.assertAlmostEqual(lag["big"], -15.6, delta=2)

    def test_chip_asks_the_host_and_reflects_what_the_host_sets(self):
        pg = self.page({"width": 388, "height": 760})
        pg.evaluate("document.querySelector('.size-opt[data-size=big]').click()")
        self.assertEqual(pg.evaluate("hostMessages.filter(m => m.type === 'size')"), [{"type": "size", "size": "big"}])
        self.assertEqual(pg.evaluate("document.documentElement.style.getPropertyValue('--pet-scale')"), "")  # 호스트가 정한다
        self.assertTrue(pg.evaluate("window.setPetSize('big')"))
        self.assertEqual(pg.evaluate("[...document.querySelectorAll('.size-opt')].map(b => b.dataset.size + ':' + b.getAttribute('aria-pressed'))"),
                         ["small:false", "medium:false", "big:true"])
        self.assertFalse(pg.evaluate("window.setPetSize('huge')"))
        self.assertEqual(pg.evaluate("document.documentElement.style.getPropertyValue('--pet-scale')"), "1.3")

    def test_browser_mode_chip_only_changes_the_css(self):
        pg = self.page({"width": 900, "height": 760}, host=False)
        pg.evaluate("document.querySelector('.size-opt[data-size=small]').click()")
        self.assertEqual(pg.evaluate("document.documentElement.style.getPropertyValue('--pet-scale')"), "0.75")
        self.assertEqual(pg.evaluate("Object.keys(localStorage).filter(k => /size/i.test(k))"), [])  # 저장하지 않는다


if __name__ == "__main__":
    unittest.main()
