"""임시 런타임과 웹 브리지로 색 설정 검증. 네이티브 펫은 실행하지 않는다."""
import os

os.environ.setdefault("RO_LANG", "source")  # 화면 문구는 번역 전 원문으로 검사한다
import json
import re
import tempfile
import unittest
from pathlib import Path

from ro import pet
from tests._pet_browser import launch_chromium

try:
    from playwright.sync_api import sync_playwright
except ImportError:
    sync_playwright = None


def initial_prefs(html):
    return json.loads(re.search(r"const INITIAL_PREFS = (.*);", html)[1])


class ColorPrefsTest(unittest.TestCase):
    def runtime(self, d):
        return pet.PetRuntime(home=d, log_dir=d, map_path=str(Path(d) / "map.json"))

    def test_only_system_light_dark_orange_are_offered(self):
        self.assertEqual(pet.PREF_CHOICES["color"], ("auto", "light", "dark", "orange"))
        self.assertEqual(pet.PREF_CHOICES["panel"], ("auto", "light", "dark"))
        for old in ("tint", "glass", "theme"):
            self.assertNotIn(old, pet.PREF_CHOICES)
        html = pet.render_html("t")
        self.assertEqual(re.findall(r'data-key="color" data-value="(\w+)"', html),
                         ["auto", "light", "dark", "orange"])
        for gone in ("Sage", "Sky", "Lilac", "#8FB39A", "#8EBBE0", "#B7A4E0"):
            self.assertNotIn(gone, html)

    def test_first_appearance_follows_the_system(self):
        self.assertEqual(initial_prefs(pet.render_html("t")), {})
        self.assertIn('let colorMode = COLOR_CHOICES.includes(INITIAL_PREFS.color) ? INITIAL_PREFS.color : "auto";',
                      pet.PET_HTML)

    def test_ro_color_is_plain_text_without_swatches_or_settings(self):
        html = pet.render_html("t", {}, "mini")
        style = html[html.index('id="paneSettings"'):html.index('id="writeCard"')]
        self.assertIn('>ro color<', style)
        labels = re.findall(r'data-key="color" data-value="\w+">([^<]+)</button>', style)
        self.assertEqual(labels, ["System", "Light", "Dark", "Orange"])
        for gone in ('swatch', 'id="prefsBtn"', 'id="panePrefs"', 'data-key="panel"', 'switchTab("prefs")'):
            self.assertNotIn(gone, html)

    def test_panel_color_is_chosen_from_the_host_menu(self):
        src = (Path(pet.__file__).parent / "pet_mac.swift").read_text(encoding="utf-8")
        self.assertIn('("panel", [("System", "auto"), ("Light", "light"), ("Dark", "dark")])', src)
        self.assertIn('NSMenuItem(title: L("Panel color")', src)

    def test_saved_old_colors_no_longer_paint_ro(self):
        with tempfile.TemporaryDirectory() as d:
            rt = self.runtime(d)
            pet.config.update(d, pet={"material": "glass", "theme": "chalk", "glass": "auto", "tint": "sage"})
            self.assertEqual(rt.prefs(), {"material": "glass"})
            self.assertEqual(initial_prefs(pet.render_html("t", rt.prefs())), {"material": "glass"})

    def test_saving_drops_old_color_keys_and_rejects_others(self):
        with tempfile.TemporaryDirectory() as d:
            rt = self.runtime(d)
            pet.config.update(d, pet={"tint": "sage", "focus": True})
            for value in pet.PREF_CHOICES["color"]:
                self.assertTrue(rt.set_prefs({"color": value})["ok"])
            self.assertEqual(pet.config.load(d)["pet"], {"focus": True, "color": "orange"})
            for value in ("sage", "</script>", None, {}, [], True):
                self.assertFalse(rt.set_prefs({"color": value})["ok"])
            self.assertEqual(self.runtime(d).prefs()["color"], "orange")

    def test_invalid_value_renders_as_no_choice(self):
        self.assertEqual(initial_prefs(pet.render_html("t", {"color": "</script>", "panel": "orange", "focus": True})), {})


@unittest.skipUnless(sync_playwright, "playwright 필요")
class ColorWebTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tmp = tempfile.TemporaryDirectory()
        cls.addClassCleanup(cls.tmp.cleanup)
        d = cls.tmp.name
        cls.rt = pet.PetRuntime(home=d, log_dir=d, map_path=str(Path(d) / "map.json"))
        cls.server = pet.start_server(cls.rt)
        cls.addClassCleanup(cls.server.server_close)
        cls.addClassCleanup(cls.server.shutdown)
        cls.url = "http://127.0.0.1:%d/" % cls.server.server_address[1]
        cls.pw = sync_playwright().start()
        cls.addClassCleanup(cls.pw.stop)
        cls.browser = launch_chromium(cls.pw)
        cls.addClassCleanup(cls.browser.close)

    def page(self, prefs, native=False, scheme="light"):
        pet.config.update(self.tmp.name, pet=prefs)
        ctx = self.browser.new_context(viewport={"width": 420, "height": 800}, reduced_motion="reduce",
                                       color_scheme=scheme)
        self.addCleanup(ctx.close)
        if native:
            ctx.add_init_script("""window.hostMessages = [];
                window.webkit = {messageHandlers: {roHost: {postMessage: m => hostMessages.push(m)}}};""")
        page = ctx.new_page()
        page.goto(self.url)
        page.wait_for_function("typeof window.setLookPref === 'function'")
        return page

    FILL = "getComputedStyle(document.querySelector('#roBot')).getPropertyValue('--bot-fill').trim()"
    EYE = "getComputedStyle(document.querySelector('#roBot')).getPropertyValue('--bot-eye').trim()"
    PANEL_DARK = "document.body.classList.contains('theme-chalk')"

    def test_system_default_follows_the_os_for_both(self):
        for scheme, dark in (("light", False), ("dark", True)):
            with self.subTest(scheme=scheme):
                page = self.page({"material": "clay"}, scheme=scheme)
                self.assertEqual(page.evaluate(self.PANEL_DARK), dark)
                self.assertEqual(page.evaluate("document.body.classList.contains('glass-dark')"), dark)
                self.assertEqual(page.evaluate(self.EYE), "#F5F2EB" if dark else "#1A1917")

    def test_ro_color_and_panel_color_change_independently(self):
        page = self.page({"material": "clay"})
        page.evaluate("setLookPref('color', 'dark')")
        self.assertEqual(page.evaluate(self.EYE), "#F5F2EB")
        self.assertFalse(page.evaluate(self.PANEL_DARK))
        page.evaluate("setLookPref('panel', 'dark')")
        self.assertTrue(page.evaluate(self.PANEL_DARK))
        page.evaluate("setLookPref('color', 'light')")
        self.assertEqual(page.evaluate(self.EYE), "#1A1917")
        self.assertTrue(page.evaluate(self.PANEL_DARK))
        page.evaluate("setLookPref('panel', 'light')")
        self.assertFalse(page.evaluate(self.PANEL_DARK))
        self.assertEqual(self.rt.prefs()["color"], "light")
        self.assertEqual(self.rt.prefs()["panel"], "light")

    def test_orange_body_keeps_ink_eyes_and_does_not_touch_the_panel(self):
        page = self.page({"material": "clay", "panel": "light"}, scheme="dark")
        page.evaluate("setLookPref('color', 'orange')")
        self.assertEqual(page.evaluate(self.FILL), "#F3874E")
        self.assertEqual(page.evaluate(self.EYE), "#1A1917")
        self.assertFalse(page.evaluate(self.PANEL_DARK))
        page.reload()
        page.wait_for_function("typeof window.setLookPref === 'function'")
        self.assertEqual(page.evaluate(self.FILL), "#F3874E")

    def test_orange_glass_is_orange_without_host_glass(self):
        page = self.page({"material": "glass", "color": "orange"})
        tint = page.evaluate("getComputedStyle(document.querySelector('.pill-head')).getPropertyValue('--g-tint-top')")
        self.assertIn("243, 135, 78", tint)

    def test_orange_glass_paints_over_native_glass(self):
        page = self.page({"material": "glass", "color": "orange"}, native=True)
        page.evaluate("setNativeGlass('liquid')")
        page.wait_for_function("document.body.classList.contains('native-glass-liquid')")
        bg = page.evaluate("getComputedStyle(document.querySelector('.pill-head')).backgroundColor")
        self.assertIn("243, 135, 78", bg)
        alpha = float(bg.rstrip(")").split(",")[-1])
        self.assertLess(alpha, 0.6, "유리는 뒤가 비쳐야 한다")

    def test_glass_host_gets_orange_tint_only_for_orange(self):
        page = self.page({"material": "glass"}, native=True)
        page.evaluate("setNativeGlass('liquid')")
        page.wait_for_function("hostMessages.some(m => m.type === 'glass' && m.on)")
        last = "hostMessages.filter(m => m.type === 'glass' && m.on).at(-1)"
        self.assertNotIn("tint", page.evaluate(last))
        page.evaluate("setLookPref('color', 'orange')")
        page.wait_for_function(f"{last}.tint === '#F3874E'")
        self.assertEqual(page.evaluate("hostMessages.filter(m => m.type === 'look').at(-1)"),
                         {"type": "look", "color": "orange", "panel": "auto"})
        page.evaluate("setLookPref('color', 'dark')")
        page.wait_for_function(f"!('tint' in {last}) && {last}.dark === true")

    def test_invalid_choice_and_failed_save_restore(self):
        page = self.page({"material": "clay", "color": "dark"}, native=True)
        page.evaluate("setLookPref('color', '__proto__'); setLookPref('tint', 'sage')")
        self.assertEqual(self.rt.prefs()["color"], "dark")
        page.route("**/api/prefs", lambda route: route.fulfill(status=200, content_type="application/json", body='{"ok":false}'))
        page.evaluate("setLookPref('color', 'orange')")
        page.wait_for_function("hostMessages.filter(m => m.type === 'look').at(-1).color === 'dark'")
        self.assertEqual(page.evaluate(self.EYE), "#F5F2EB")
        self.assertEqual(self.rt.prefs()["color"], "dark")
        self.assertIn("reverted", page.locator("#toast").inner_text())


if __name__ == "__main__":
    unittest.main()
