"""판매 사이트(site/, docs/SITE-PLAN.md P4): 정적 페이지가 서로 잘 이어지고, 외부 요청 없이 뜨고, 결제 링크가 비면 버튼이 꺼져 있다."""
import functools
import http.server
import re
import threading
import unittest
from html.parser import HTMLParser
from pathlib import Path

from tests._pet_browser import launch_chromium

try:
    from playwright.sync_api import sync_playwright
except ImportError:  # 선택 의존성
    sync_playwright = None

SITE = Path(__file__).resolve().parent.parent / "site"
PAGES = ["index.html", "pro/index.html", "thanks/index.html", "license/index.html",
         "privacy/index.html", "terms/index.html", "refund/index.html"]
# 사이트 밖으로 거는 링크는 여기만(비공개 ro.bot 저장소 링크는 방문자에게 404, 기획서 '위험')
EXTERNAL_OK = ("https://github.com/rhochoi/ro-pet/", "https://polar.sh/")


class _Refs(HTMLParser):
    def __init__(self):
        super().__init__()
        self.refs = []  # (tag, attr, value)

    def handle_starttag(self, tag, attrs):
        for k, v in attrs:
            if k in ("href", "src") and v is not None:
                self.refs.append((tag, k, v))


def refs(page):
    p = _Refs()
    p.feed((SITE / page).read_text(encoding="utf-8"))
    return p.refs


class SiteStaticTest(unittest.TestCase):
    def test_pages_exist_with_title_and_viewport(self):
        for page in PAGES:
            html = (SITE / page).read_text(encoding="utf-8")
            self.assertRegex(html, r"<title>[^<]+</title>", page)
            self.assertIn('name="viewport"', html, page)
            self.assertIn('<html lang="en">', html, page)

    def test_local_links_resolve(self):
        for page in PAGES:
            base = (SITE / page).parent
            for tag, attr, value in refs(page):
                if value.startswith(("http://", "https://", "mailto:", "#")):
                    continue
                target = (base / value.split("#")[0]).resolve()
                if value == "" or value.endswith("/"):
                    target = target / "index.html"
                self.assertTrue(target.exists(), f"{page}: {tag} {attr}={value!r}")
                self.assertTrue(SITE.resolve() in target.parents or target.parent == SITE.resolve(), value)

    def test_no_external_resources_and_only_known_links(self):
        for page in PAGES:
            for tag, attr, value in refs(page):
                if tag in ("script", "link", "img"):  # 방문자 IP가 다른 곳으로 가지 않는다(폰트·분석 없음)
                    self.assertFalse(value.startswith(("http:", "https:", "//")), f"{page}: {value}")
                elif value.startswith(("http:", "https:")):
                    self.assertTrue(value.startswith(EXTERNAL_OK), f"{page}: {value}")
            self.assertNotIn("rhochoi/ro.bot", (SITE / page).read_text(encoding="utf-8"))

    def test_prices_and_promises_match_the_plan(self):
        pro = (SITE / "pro/index.html").read_text(encoding="utf-8")
        for text in ("$24 <span>/ year</span>", "$3 <span>/ month</span>", "$19 for the first year", "14-day refund",
                     "Apple Silicon", "macOS 13", "86–90%", "90–92%", "2026-10-30"):
            self.assertIn(text, pro)
        for page in ("terms/index.html", "refund/index.html"):
            html = (SITE / page).read_text(encoding="utf-8")
            self.assertIn("14 days", html)
            self.assertIn("keeps working until", html)  # 오프라인 키라 환불·해지 뒤에도 기한까지 유효

    def test_unfilled_checkout_keeps_buttons_off(self):
        cfg = (SITE / "site-config.js").read_text(encoding="utf-8")
        for name in ("yearly", "monthly"):
            value = re.search(rf'{name}: "([^"]*)"', cfg).group(1)
            self.assertTrue(value == "" or value.startswith("https://"), name)
        pro = (SITE / "pro/index.html").read_text(encoding="utf-8")
        self.assertEqual(pro.count('aria-disabled="true">Coming soon'), 2)
        self.assertNotIn('data-checkout="yearly" href', pro)   # 링크는 설정을 채웠을 때만 스크립트가 붙인다

    def test_legal_drafts_are_marked(self):
        for page in ("privacy/index.html", "terms/index.html", "refund/index.html"):
            self.assertIn('class="draft"', (SITE / page).read_text(encoding="utf-8"), page)


def _lum(hexcolor):
    c = [int(hexcolor.lstrip("#")[i:i + 2], 16) / 255 for i in (0, 2, 4)]
    c = [x / 12.92 if x <= 0.03928 else ((x + 0.055) / 1.055) ** 2.4 for x in c]
    return 0.2126 * c[0] + 0.7152 * c[1] + 0.0722 * c[2]


def contrast(a, b):
    hi, lo = sorted([_lum(a), _lum(b)], reverse=True)
    return (hi + 0.05) / (lo + 0.05)


class SiteDesignTest(unittest.TestCase):
    """브랜드 약속을 화면 규칙으로 고정한다: 읽히는 대비, 움직임을 멈출 수 있음, 데모도 외부로 보내지 않음."""

    def tokens(self):
        css = (SITE / "assets/site.css").read_text(encoding="utf-8")
        light = dict(re.findall(r"--([a-z-]+):\s*(#[0-9A-Fa-f]{6})", css.split("@media (prefers-color-scheme: dark)")[0]))
        dark_block = css.split("@media (prefers-color-scheme: dark)")[1].split("}\n}")[0]
        dark = {**light, **dict(re.findall(r"--([a-z-]+):\s*(#[0-9A-Fa-f]{6})", dark_block))}
        return light, dark

    def test_text_contrast_meets_wcag_aa(self):
        for name, t in zip(("light", "dark"), self.tokens()):
            for fg, bg in (("ink", "paper"), ("muted", "paper"), ("muted", "card"), ("notice", "paper")):
                self.assertGreaterEqual(contrast(t[fg], t[bg]), 4.5, f"{name}: {fg} on {bg}")
            self.assertGreaterEqual(contrast(t["paper"], t["ink"]), 4.5, f"{name}: button")

    def test_ro_follows_the_brand_mark(self):
        # "ro pet viz": ro는 먹 층(다크에선 크림), 왼쪽 정렬. 사이트에 주황은 없다
        css = (SITE / "assets/site.css").read_text(encoding="utf-8")
        demo = (SITE / "demo-src/ro-hero.css").read_text(encoding="utf-8")
        for text in (css, demo):
            self.assertNotIn("F3874E", text.upper())
        self.assertIn(".ro-mark .ro-b { fill: var(--ink); }", css)       # 다크 모드면 토큰이 뒤집혀 크림 ro
        self.assertIn("align-items: flex-start", demo)                  # 층은 왼쪽에 맞춘다
        for page in PAGES:
            self.assertIn('class="ro-mark', (SITE / page).read_text(encoding="utf-8"), page)
        fav = (SITE / "assets/favicon.svg").read_text(encoding="utf-8")
        self.assertIn('viewBox="0 0 16 16"', fav)                        # 16px 전용 픽셀 버전

    def test_demo_is_static_pausable_and_described(self):
        js = (SITE / "assets/ro-hero/ro-hero.js").read_text(encoding="utf-8")
        for call in ("fetch(", "XMLHttpRequest", "WebSocket", "sendBeacon"):
            self.assertNotIn(call, js)
        main = (SITE / "demo-src/main.tsx").read_text(encoding="utf-8")
        self.assertIn('role="img" aria-label={LABEL}', main)
        self.assertIn("Pause animation", main)            # WCAG 2.2.2: 5초 넘게 움직이면 멈출 수 있어야
        self.assertIn("prefers-reduced-motion", main)     # OS가 동작 줄이기면 처음부터 정지 화면
        pro = (SITE / "pro/index.html").read_text(encoding="utf-8")
        self.assertRegex(pro, r'<div id="ro-hero" class="demo-stage">\s*<svg')  # JS 없이도 그림이 남는다
        css = (SITE / "assets/site.css").read_text(encoding="utf-8")
        self.assertIn("aspect-ratio: 720 / 380", css)     # 스크립트가 늦게 와도 아래가 밀리지 않게 자리를 잡아 둔다
        self.assertIn("aspect-ratio: 358 / 520", css)
        self.assertTrue((SITE / "demo-src/kit/LICENSE").exists())


class SiteTruthTest(unittest.TestCase):
    """2026-11-20 리뷰에서 나온 것: 사이트 문구가 실제 앱·빌드·발급 메일과 같아야 한다."""
    ROOT = SITE.parent

    def read(self, rel):
        return (self.ROOT / rel).read_text(encoding="utf-8")

    def test_demo_ro_stays_visible_in_dark_mode(self):
        css = self.read("site/demo-src/ro-hero.css")
        # 넓은 화면에서 ro는 흰 창 위에 있으니 먹 그대로, 페이지 위에 있는 compact에서만 반전
        self.assertIn('.ss-stage[data-layout="compact"] .rh-pet { --pill: #F4F0E8', css)
        self.assertNotIn("@media (prefers-color-scheme: dark) { .rh-pet {", css)

    def test_sentences_read_whole_without_the_portal_link(self):
        for page in ("site/license/index.html", "site/refund/index.html"):
            html = self.read(page)
            self.assertNotRegex(html, r"the <a data-portal|Use the <a data-portal")
            self.assertRegex(html, r"<p><a data-portal hidden>[^<]+</a></p>")  # 링크는 따로 한 줄

    def test_privacy_says_what_the_updater_does(self):
        build = self.read("scripts/build-app.sh")
        privacy = self.read("site/privacy/index.html")
        if "<key>SUAutomaticallyUpdate</key><true/>" in build:
            self.assertIn("installs it automatically", privacy)
            self.assertNotIn("if you agree", privacy)

    def test_license_page_matches_the_mail_subject(self):
        worker = self.read("issuer/worker.js")
        subject = re.search(r'subject: "([^"]+)"', worker).group(1)
        self.assertIn('"License key" in the subject', self.read("site/license/index.html"))
        self.assertIn("License key", subject)

    def test_demo_uses_the_apps_own_words(self):
        demo = self.read("site/demo-src/RoHero.tsx")
        i18n = self.read("ro/pet_ui/i18n.js")
        placeholder = re.search(r'placeholder="([^"]+)"', demo).group(1)
        self.assertIn(f'"{placeholder}"', i18n)
        for why in re.findall(r'why: "([^"]+)"', demo):
            self.assertRegex(why, r"^(Name starts with|Name contains|Whole name matches) '")
            self.assertIn(why.split(" '")[0], i18n)

    def test_promises_admit_the_license_pickup(self):
        # ro/licensenet.py가 있는 한, "아무것도 안 나간다"고 쓰지 않고 무엇을 언제 보내는지 적는다
        if not (self.ROOT / "ro/licensenet.py").exists():
            return
        privacy, pro, readme = self.read("site/privacy/index.html"), self.read("site/pro/index.html"), self.read("README.md")
        self.assertIn("random install ID", privacy)
        self.assertIn("once a day while pro is on", privacy)
        self.assertIn("turn this off", privacy)
        self.assertNotIn("Nothing leaves your Mac", pro)
        self.assertNotIn("keeps no database", privacy)
        self.assertIn("ro/licensenet.py", readme)
        self.assertNotIn("인터넷은 직접 `ro update`를 실행할 때만", readme)

    def test_name_is_lowercase_ro(self):
        css = self.read("site/assets/site.css")
        self.assertNotIn("text-transform: uppercase", css)
        self.assertNotIn("the pet's", self.read("site/pro/index.html"))


@unittest.skipUnless(sync_playwright, "playwright 필요")
class SiteBrowserTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        handler = functools.partial(_QuietHandler, directory=str(SITE))
        cls.httpd = http.server.ThreadingHTTPServer(("127.0.0.1", 0), handler)
        threading.Thread(target=cls.httpd.serve_forever, daemon=True).start()
        cls.addClassCleanup(cls.httpd.server_close)
        cls.addClassCleanup(cls.httpd.shutdown)
        cls.base = f"http://127.0.0.1:{cls.httpd.server_address[1]}/"
        cls.pw = sync_playwright().start()
        cls.addClassCleanup(cls.pw.stop)
        cls.browser = launch_chromium(cls.pw)
        cls.addClassCleanup(cls.browser.close)

    def open(self, path, width):
        ctx = self.browser.new_context(viewport={"width": width, "height": 900})
        self.addCleanup(ctx.close)
        page = ctx.new_page()
        requests = []
        page.on("request", lambda r: requests.append(r.url))
        page.goto(self.base + path)
        return page, requests

    def test_no_horizontal_scroll_and_same_origin_only(self):
        for path in ("", "pro/", "thanks/", "license/", "privacy/", "terms/", "refund/"):
            for width in (375, 1280):
                page, requests = self.open(path, width)
                overflow = page.evaluate("document.documentElement.scrollWidth - document.documentElement.clientWidth")
                self.assertLessEqual(overflow, 0, f"{path} @ {width}px")
                self.assertTrue(all(u.startswith(self.base) for u in requests), requests)

    def test_filled_checkout_turns_buttons_on(self):
        page, _ = self.open("pro/", 1280)
        self.assertEqual(page.get_attribute('[data-checkout="yearly"]', "aria-disabled"), "true")
        page.evaluate("""() => { RO_SITE.checkout.yearly = 'https://buy.polar.sh/test';
                                 RO_SITE.checkout.monthly = 'javascript:alert(1)';
                                 RO_SITE.support = 'help@example.test'; RO_SITE_APPLY(); }""")
        y = '[data-checkout="yearly"]'
        self.assertEqual(page.get_attribute(y, "href"), "https://buy.polar.sh/test")
        self.assertIsNone(page.get_attribute(y, "aria-disabled"))
        self.assertEqual(page.text_content(y), "Get pro — yearly")
        self.assertIsNone(page.get_attribute('[data-checkout="monthly"]', "href"))  # https가 아니면 켜지지 않는다
        page, _ = self.open("license/", 1280)
        page.evaluate("() => { RO_SITE.support = 'help@example.test'; RO_SITE_APPLY(); }")
        self.assertEqual(page.get_attribute("[data-support]", "href"), "mailto:help@example.test")
        self.assertTrue(page.is_hidden("[data-portal]"))  # 포털 주소가 없으면 링크를 숨긴다


class _QuietHandler(http.server.SimpleHTTPRequestHandler):
    def log_message(self, *args):
        pass


if __name__ == "__main__":
    unittest.main()
