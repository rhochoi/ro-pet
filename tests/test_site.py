"""판매 사이트(site/, docs/SITE-PLAN.md P4): 정적 페이지가 서로 잘 이어지고, 외부 요청 없이 뜨고, 결제 링크가 비면 버튼이 꺼져 있다."""
import functools
import http.server
import re
import shutil
import subprocess
import sys
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
            self.assertIn("keeps working until", html)  # 확인된 결제는 환불·해지 뒤에도 기한까지 유효

    def test_unfilled_checkout_keeps_buttons_off(self):
        cfg = (SITE / "site-config.js").read_text(encoding="utf-8")
        for name in ("yearly", "monthly"):
            value = re.search(rf'{name}: "([^"]*)"', cfg).group(1)
            self.assertTrue(value == "" or value.startswith("https://"), name)
        pro = (SITE / "pro/index.html").read_text(encoding="utf-8")
        self.assertEqual(pro.count('aria-disabled="true">Coming soon'), 2)
        self.assertNotIn('data-checkout="yearly" href', pro)   # 링크는 설정을 채웠을 때만 스크립트가 붙인다

    def test_legal_pages_are_finalized(self):
        for page in ("privacy/index.html", "terms/index.html", "refund/index.html"):
            self.assertNotIn("Nothing is for sale yet", (SITE / page).read_text(encoding="utf-8"), page)


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


class SiteRoamStaticTest(unittest.TestCase):
    """사이트를 돌아다니는 ro(site/assets/ro-roam): 모든 쪽에 붙고, 요청을 보내지 않고, 먼저 말하지 않는다."""
    JS = SITE / "assets/ro-roam/ro-roam.js"
    CSS = SITE / "assets/ro-roam/ro-roam.css"

    def test_every_page_loads_ro_from_its_own_origin(self):
        for page in PAGES:
            html = (SITE / page).read_text(encoding="utf-8")
            depth = "" if page == "index.html" else "../"
            self.assertIn(f'<script src="{depth}assets/ro-roam/ro-roam.js"', html, page)
            self.assertIn(f'href="{depth}assets/ro-roam/ro-roam.css"', html, page)
        self.assertIn('data-page="home"', (SITE / "index.html").read_text(encoding="utf-8"))
        self.assertIn('data-page="pro"', (SITE / "pro/index.html").read_text(encoding="utf-8"))

    def test_roam_sends_nothing_and_stores_little(self):
        js = self.JS.read_text(encoding="utf-8")
        for call in ("fetch(", "XMLHttpRequest", "WebSocket", "sendBeacon", "localStorage", "document.cookie", "new Image"):
            self.assertNotIn(call, js)
        self.assertIn("sessionStorage", js)                  # 서 있던 자리와 쉬기 선택만, 탭을 닫으면 사라진다

    def test_roam_respects_motion_and_brand(self):
        js, css = self.JS.read_text(encoding="utf-8"), self.CSS.read_text(encoding="utf-8")
        self.assertIn("prefers-reduced-motion", js)          # 동작 줄이기면 돌아다니지 않는다
        self.assertIn("Let ro rest", js)                     # WCAG 2.2.2: 움직임을 멈출 수 있다
        self.assertIn("Alt+R", js)                           # 앱과 같은 ⌥R
        for text in (js, css):
            self.assertNotIn("F3874E", text.upper())          # 사이트에 주황은 없다
        self.assertIn('class: "ro-mark rr-svg"', js)         # 같은 ro 마크(먹 층, 다크에선 반전)

    def test_roam_never_speaks_first(self):
        js = self.JS.read_text(encoding="utf-8")
        # 말풍선은 사용자의 행동(클릭·단축키·질문)에서만 열린다. 타이머가 openPanel/respond를 부르지 않는다
        for line in js.splitlines():
            if "setInterval" in line or "setTimeout" in line:
                self.assertNotIn("openPanel()", line)
        self.assertNotIn("setInterval(openPanel", js)


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
        for page in ("site/refund/index.html",):
            html = self.read(page)
            self.assertNotRegex(html, r"the <a data-portal|Use the <a data-portal")
            self.assertRegex(html, r"<p><a data-portal hidden>[^<]+</a></p>")  # 링크는 따로 한 줄

    def test_privacy_says_what_the_updater_does(self):
        build = self.read("scripts/build-app.sh")
        privacy = self.read("site/privacy/index.html")
        if "<key>SUAutomaticallyUpdate</key><true/>" in build:
            self.assertIn("installs it automatically", privacy)
            self.assertNotIn("if you agree", privacy)

    def test_no_license_key_wording_for_visitors(self):
        # 2026-11-23: 라이선스 키는 사용자에게서 없앴다. 결제하면 앱이 설치 토큰으로 스스로 pro가 된다
        for page in PAGES:
            html = (SITE / page).read_text(encoding="utf-8")
            self.assertNotRegex(html, r"RO1\.|Save key|[Pp]aste the key|License…|License help", page)
        self.assertIn("../pro/#help", (SITE / "license/index.html").read_text(encoding="utf-8"))  # 옛 링크는 /pro로

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


class SiteInteractiveSandboxTest(unittest.TestCase):
    """Track B: 살아 있는 인터랙티브 웹 펫(site/index.html)과 로컬 샌드박스 체험판(site/pro/index.html) 검증."""

    def test_interactive_scripts_have_zero_network_calls(self):
        for rel in ("assets/web-pet.js", "assets/ro-sandbox.js"):
            js = (SITE / rel).read_text(encoding="utf-8")
            for call in ("fetch(", "XMLHttpRequest", "WebSocket", "sendBeacon", "http://", "https://"):
                self.assertNotIn(call, js, f"{rel} contains network primitive {call!r}")

    def test_web_pet_and_pro_sandbox_markup_present(self):
        idx = (SITE / "index.html").read_text(encoding="utf-8")
        for marker in ('id="web-pet-playground"', 'id="webPetStage"', 'id="webPetWrap"', 'data-wp-mat="clay"',
                       'data-wp-mat="glass"', 'data-wp-color="orange"', 'data-wp-size="big"', 'data-wp-mood="discovery"',
                       'id="webPetPauseBtn"'):
            self.assertIn(marker, idx)
        pro = (SITE / "pro/index.html").read_text(encoding="utf-8")
        for marker in ('id="pro-sandbox"', 'id="sandboxTabSearch"', 'id="sandboxTabTidy"', 'id="sandboxSearchInput"',
                       'id="sandboxResults"', 'id="sandboxPreview"', 'id="sandboxApproveBtn"', 'id="sandboxUndoBtn"',
                       'id="sandboxTidyList"'):
            self.assertIn(marker, pro)

    def test_web_pet_interactions_and_latency_under_100ms(self):
        import json
        import shutil
        import subprocess
        if not shutil.which("node"):
            self.skipTest("node 필요")
        web_pet_js = (SITE / "assets/web-pet.js").read_text(encoding="utf-8")
        script = r"""
const assert = require('node:assert/strict');
function makeEl(id = '') {
  const attrs = new Map();
  const classes = new Set();
  const styles = new Map();
  const listeners = {};
  return {
    id,
    textContent: '',
    innerHTML: '',
    hidden: false,
    disabled: false,
    classList: {
      toggle(c, on) { if (on === undefined) on = !classes.has(c); if (on) classes.add(c); else classes.delete(c); },
      add(c) { classes.add(c); },
      remove(c) { classes.delete(c); },
      contains(c) { return classes.has(c); }
    },
    style: {
      transform: '',
      setProperty(k, v) { styles.set(k, String(v)); },
      getPropertyValue(k) { return styles.get(k) || ''; },
      removeProperty(k) { styles.delete(k); }
    },
    setAttribute(k, v) { attrs.set(k, String(v)); },
    getAttribute(k) { return attrs.has(k) ? attrs.get(k) : null; },
    removeAttribute(k) { attrs.delete(k); },
    addEventListener(ev, fn) { (listeners[ev] = listeners[ev] || []).push(fn); },
    getBoundingClientRect() { return { left: 100, top: 100, width: 80, height: 32 }; }
  };
}
const nodes = {
  '#webPetStage': makeEl('webPetStage'),
  '#webPetWrap': makeEl('webPetWrap'),
  '#webPetHead': makeEl('webPetHead'),
  '#webPetBody': makeEl('webPetBody'),
  '#webPetBase': makeEl('webPetBase'),
  '#webPetEyes': makeEl('webPetEyes'),
  '#webPetEyeL': makeEl('webPetEyeL'),
  '#webPetEyeR': makeEl('webPetEyeR'),
  '#webPetStatus': makeEl('webPetStatus'),
  '#webPetPauseBtn': makeEl('webPetPauseBtn'),
};
const root = {
  querySelector(sel) { return nodes[sel] || null; },
  querySelectorAll() { return []; }
};
global.window = { matchMedia: () => ({ matches: false, addEventListener() {} }) };
global.document = { readyState: 'complete', getElementById: () => root };
""" + web_pet_js + r"""
const pet = window.RoWebPet;
assert.ok(pet, 'RoWebPet initialized');
const latencies = [];
pet.setMaterial('glass'); latencies.push(pet.state.lastLatencyMs);
assert.equal(nodes['#webPetWrap'].getAttribute('data-material'), 'glass');
pet.setColor('orange'); latencies.push(pet.state.lastLatencyMs);
assert.equal(nodes['#webPetWrap'].getAttribute('data-color'), 'orange');
pet.setSize('big'); latencies.push(pet.state.lastLatencyMs);
assert.equal(nodes['#webPetStage'].style.getPropertyValue('--wp-scale'), '1.24');
pet.setMood('discovery'); latencies.push(pet.state.lastLatencyMs);
assert.equal(nodes['#webPetWrap'].getAttribute('data-mood'), 'discovery');
pet.setMood('idle');
pet.gazeAt(220, 140); latencies.push(pet.state.lastLatencyMs);
assert.notEqual(pet.state.gaze.dx, 0);
pet.press(); latencies.push(pet.state.lastLatencyMs);
assert.equal(nodes['#webPetWrap'].getAttribute('data-action'), 'press');
// Rubbing head back and forth triggers pet
[100, 120, 95, 125, 90].forEach((x, i) => pet.feedStroke(x, i * 80));
latencies.push(pet.state.lastLatencyMs);
assert.equal(nodes['#webPetWrap'].getAttribute('data-action'), 'pet');
pet.togglePause(true);
assert.equal(pet.state.paused, true);
console.log(JSON.stringify({ ok: true, maxLatencyMs: Math.max(...latencies), interactions: pet.state.interactions }));
"""
        r = subprocess.run(["node", "-e", script], capture_output=True, text=True, timeout=10)
        self.assertEqual(r.returncode, 0, r.stderr)
        out = json.loads(r.stdout.strip())
        self.assertTrue(out["ok"])
        self.assertLessEqual(out["maxLatencyMs"], 100.0)
        self.assertGreaterEqual(out["interactions"], 6)

    def test_pro_sandbox_search_and_tidy_apply_undo_under_100ms(self):
        import json
        import shutil
        import subprocess
        if not shutil.which("node"):
            self.skipTest("node 필요")
        sandbox_js = (SITE / "assets/ro-sandbox.js").read_text(encoding="utf-8")
        script = r"""
const assert = require('node:assert/strict');
function makeEl(id = '') {
  return {
    id, value: '', textContent: '', innerHTML: '', hidden: false, disabled: false,
    classList: { toggle() {}, add() {}, remove() {} },
    setAttribute() {}, getAttribute() { return null; }, addEventListener() {}, appendChild() {}, querySelector() { return null; }
  };
}
const els = {
  '#sandboxTabSearch': makeEl('sandboxTabSearch'),
  '#sandboxTabTidy': makeEl('sandboxTabTidy'),
  '#sandboxSearchView': makeEl('sandboxSearchView'),
  '#sandboxTidyView': makeEl('sandboxTidyView'),
  '#sandboxSearchInput': makeEl('sandboxSearchInput'),
  '#sandboxResults': makeEl('sandboxResults'),
  '#sandboxPreview': makeEl('sandboxPreview'),
  '#sandboxSearchMeta': makeEl('sandboxSearchMeta'),
  '#sandboxTidyList': makeEl('sandboxTidyList'),
  '#sandboxTidyStatus': makeEl('sandboxTidyStatus'),
  '#sandboxApproveBtn': makeEl('sandboxApproveBtn'),
  '#sandboxUndoBtn': makeEl('sandboxUndoBtn'),
  '#sandboxResetBtn': makeEl('sandboxResetBtn'),
  '#sandboxPet': makeEl('sandboxPet'),
};
const root = {
  querySelector(s) { return els[s] || null; },
  querySelectorAll() { return []; }
};
global.window = { addEventListener() {} };
global.document = {
  readyState: 'complete',
  getElementById: () => root,
  createElement: () => makeEl()
};
""" + sandbox_js + r"""
const sb = window.RoProSandbox;
assert.ok(sb, 'RoProSandbox initialized');
const allFiles = sb.getFiles();
assert.ok(allFiles.length >= 15 && allFiles.length <= 25, '15~25 virtual files');
const latencies = [];

// 1. Search by kind & time
const r1 = sb.search('contract pdf last month');
latencies.push(sb.state.lastLatencyMs);
assert.ok(r1.length >= 2);
assert.equal(r1[0].name, 'contract_final_v2.pdf');

// 2. Search by OCR / document content
const r2 = sb.search('whiteboard OCR TactGate');
latencies.push(sb.state.lastLatencyMs);
assert.ok(r2.some(x => x.name === 'IMG_4092_whiteboard_scan.png'));

// 3. Tidy preview -> approve apply -> 1-click undo -> 100% restored
const before = JSON.stringify(sb.getFiles());
sb.setMode('tidy');
latencies.push(sb.state.lastLatencyMs);
const batch = sb.applyTidy();
latencies.push(sb.state.lastLatencyMs);
assert.ok(batch && batch.movedCount >= 5 && batch.heldCount >= 4);
const afterApply = JSON.stringify(sb.getFiles());
assert.notEqual(afterApply, before, 'applyTidy moves approved files');

const restoredCount = sb.undoTidy();
latencies.push(sb.state.lastLatencyMs);
assert.equal(restoredCount, batch.movedCount + batch.heldCount);
const afterUndo = JSON.stringify(sb.getFiles());
assert.equal(afterUndo, before, '1-click undo restores 100% of files to original folder and name');

console.log(JSON.stringify({
  ok: true,
  fileCount: allFiles.length,
  maxLatencyMs: Math.max(...latencies),
  moved: batch.movedCount,
  held: batch.heldCount,
  restored: restoredCount
}));
"""
        r = subprocess.run(["node", "-e", script], capture_output=True, text=True, timeout=10)
        self.assertEqual(r.returncode, 0, r.stderr)
        out = json.loads(r.stdout.strip())
        self.assertTrue(out["ok"])
        self.assertGreaterEqual(out["fileCount"], 15)
        self.assertLessEqual(out["fileCount"], 25)
        self.assertLessEqual(out["maxLatencyMs"], 100.0)
        self.assertEqual(out["restored"], out["moved"] + out["held"])

    @unittest.skipUnless(sys.platform == "darwin" and shutil.which("swift"), "macOS swift/WKWebView 필요")
    def test_webkit_zero_horizontal_scroll_and_live_dom_interactions(self):
        swift_code = r'''
import AppKit
import Foundation
import WebKit

final class NavDel: NSObject, WKNavigationDelegate {
    var done = false
    func webView(_ webView: WKWebView, didFinish navigation: WKNavigation!) { done = true }
}

let app = NSApplication.shared
app.setActivationPolicy(.prohibited)
let siteDir = URL(fileURLWithPath: CommandLine.arguments[1])
let pages = ["index.html", "pro/index.html", "thanks/index.html", "license/index.html", "privacy/index.html", "terms/index.html", "refund/index.html"]
let widths: [CGFloat] = [375, 1280]
var failures: [String] = []

for page in pages {
    for w in widths {
        let wv = WKWebView(frame: NSRect(x: 0, y: 0, width: w, height: 900))
        let del = NavDel()
        wv.navigationDelegate = del
        wv.loadFileURL(siteDir.appendingPathComponent(page), allowingReadAccessTo: siteDir)
        let deadline = Date().addingTimeInterval(6.0)
        while !del.done && Date() < deadline {
            RunLoop.current.run(mode: .default, before: Date().addingTimeInterval(0.015))
        }
        let settle = Date().addingTimeInterval(0.08)
        while Date() < settle {
            RunLoop.current.run(mode: .default, before: Date().addingTimeInterval(0.015))
        }
        var evalDone = false
        var jsScript = "({ overflow: Math.max(0, document.documentElement.scrollWidth - document.documentElement.clientWidth) })"
        if page == "index.html" && w == 1280 {
            jsScript = """
            (() => {
              document.querySelector('[data-wp-mat="glass"]').click();
              document.querySelector('[data-wp-color="orange"]').click();
              document.getElementById('webPetWrap').click();
              const wrap = document.getElementById('webPetWrap');
              return {
                overflow: Math.max(0, document.documentElement.scrollWidth - document.documentElement.clientWidth),
                mat: wrap.getAttribute('data-material'),
                color: wrap.getAttribute('data-color'),
                action: wrap.getAttribute('data-action')
              };
            })()
            """
        } else if page == "pro/index.html" && w == 1280 {
            jsScript = """
            (() => {
              const inp = document.getElementById('sandboxSearchInput');
              inp.value = 'whiteboard OCR';
              inp.dispatchEvent(new Event('input', { bubbles: true }));
              const resText = document.getElementById('sandboxResults').textContent;
              document.getElementById('sandboxTabTidy').click();
              document.getElementById('sandboxApproveBtn').click();
              const afterApprove = document.getElementById('sandboxTidyStatus').textContent;
              document.getElementById('sandboxUndoBtn').click();
              const afterUndo = document.getElementById('sandboxTidyStatus').textContent;
              return {
                overflow: Math.max(0, document.documentElement.scrollWidth - document.documentElement.clientWidth),
                hasOcrHit: resText.includes('IMG_4092_whiteboard_scan.png'),
                committed: afterApprove.includes('Journal V2 committed'),
                undone: afterUndo.includes('Undone')
              };
            })()
            """
        }
        wv.evaluateJavaScript(jsScript) { res, err in
            if let dict = res as? [String: Any] {
                let ov = (dict["overflow"] as? Int) ?? 999
                if ov > 0 { failures.append("\(page)@\(Int(w))px overflow=\(ov)") }
                if page == "index.html" && w == 1280 {
                    if (dict["mat"] as? String) != "glass" || (dict["color"] as? String) != "orange" || (dict["action"] as? String) != "press" {
                        failures.append("index.html interaction mismatch: \(dict)")
                    }
                }
                if page == "pro/index.html" && w == 1280 {
                    if (dict["hasOcrHit"] as? Bool) != true || (dict["committed"] as? Bool) != true || (dict["undone"] as? Bool) != true {
                        failures.append("pro/index.html sandbox mismatch: \(dict)")
                    }
                }
            } else {
                failures.append("\(page)@\(Int(w))px eval error: \(String(describing: err))")
            }
            evalDone = true
        }
        let evDeadline = Date().addingTimeInterval(3.0)
        while !evalDone && Date() < evDeadline {
            RunLoop.current.run(mode: .default, before: Date().addingTimeInterval(0.015))
        }
    }
}
if failures.isEmpty {
    print("WEBKIT_OK")
} else {
    print("WEBKIT_FAIL: " + failures.joined(separator: "; "))
    exit(1)
}
'''
        r = subprocess.run(["swift", "-e", swift_code, str(SITE)], capture_output=True, text=True, timeout=45)
        self.assertEqual(r.returncode, 0, f"WebKit validation failed:\nstdout={r.stdout}\nstderr={r.stderr}")
        self.assertIn("WEBKIT_OK", r.stdout)


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
                if path == "license/":
                    page.wait_for_url("**/pro/**")   # 옛 주소는 /pro로 넘어간다. 넘어간 쪽을 잰다
                overflow = page.evaluate("document.documentElement.scrollWidth - document.documentElement.clientWidth")
                self.assertLessEqual(overflow, 0, f"{path} @ {width}px")
                self.assertTrue(all(u.startswith(self.base) for u in requests), requests)

    def test_ro_walks_the_page_and_answers_from_the_page(self):
        page, requests = self.open("", 1280)
        page.wait_for_selector("#rr-root .rr-body")
        self.assertIn("rr-live", page.get_attribute("html", "class"))
        page.keyboard.press("Alt+r")
        page.wait_for_selector(".rr-panel", state="visible", timeout=5000)
        page.fill("#rr-q", "how much is pro")
        page.keyboard.press("Enter")
        page.wait_for_function("document.querySelector('.rr-say').textContent.includes('Prices are in USD')", timeout=5000)
        self.assertIn("$3 a month", page.text_content(".rr-say"))
        page.fill("#rr-q", "weather forecast tomorrow")
        page.keyboard.press("Enter")
        page.wait_for_function("document.querySelector('.rr-say').textContent.includes('or the download')", timeout=5000)
        page.keyboard.press("Escape")
        self.assertTrue(page.is_hidden(".rr-panel"))
        self.assertTrue(all(u.startswith(self.base) for u in requests), requests)

    def test_ro_rests_and_reduced_motion_keeps_it_home(self):
        page, _ = self.open("pro/", 1280)
        page.wait_for_selector(".rr-toggle")
        page.click(".rr-toggle")
        self.assertEqual(page.get_attribute(".rr-toggle", "aria-pressed"), "true")
        self.assertTrue(page.evaluate("RO_ROAM.state().rest"))
        ctx = self.browser.new_context(viewport={"width": 1280, "height": 900}, reduced_motion="reduce")
        self.addCleanup(ctx.close)
        calm = ctx.new_page()
        calm.goto(self.base)
        calm.wait_for_selector("#rr-root .rr-body")
        calm.wait_for_timeout(3500)
        self.assertEqual(calm.evaluate("RO_ROAM.state().perch"), "home")    # 동작 줄이기: 히어로 카드에서 나가지 않는다
        self.assertTrue(calm.is_hidden(".rr-toggle"))

    def test_ro_fits_small_screens_on_every_page(self):
        for path in ("", "pro/", "privacy/"):
            page, _ = self.open(path, 375)
            page.wait_for_selector("#rr-root .rr-body")
            page.keyboard.press("Alt+r")
            page.wait_for_selector(".rr-panel", state="visible")
            box = page.eval_on_selector(".rr-panel", "e => { const r = e.getBoundingClientRect(); return [r.left, r.right]; }")
            self.assertGreaterEqual(box[0], 0, path)
            self.assertLessEqual(box[1], 375, path)

    def test_filled_checkout_turns_buttons_on(self):
        page, _ = self.open("pro/", 1280)
        page.evaluate("""() => { RO_SITE.checkout.yearly = 'https://buy.polar.sh/test';
                                 RO_SITE.checkout.monthly = 'javascript:alert(1)';
                                 RO_SITE.support = 'help@example.test';
                                 const m = document.querySelector('[data-checkout="monthly"]');
                                 m.removeAttribute('href'); m.setAttribute('aria-disabled', 'true');
                                 RO_SITE_APPLY(); }""")
        y = '[data-checkout="yearly"]'
        self.assertEqual(page.get_attribute(y, "href"), "https://buy.polar.sh/test")
        self.assertIsNone(page.get_attribute(y, "aria-disabled"))
        self.assertEqual(page.text_content(y), "Get pro — yearly")
        self.assertIsNone(page.get_attribute('[data-checkout="monthly"]', "href"))  # https가 아니면 켜지지 않는다
        page, _ = self.open("thanks/", 1280)
        page.evaluate("() => { RO_SITE.support = 'help@example.test'; RO_SITE_APPLY(); }")
        self.assertEqual(page.get_attribute("[data-support]", "href"), "mailto:help@example.test")
        self.assertTrue(page.is_hidden("[data-portal]"))  # 포털 주소가 없으면 링크를 숨긴다

    def test_interactive_web_pet_and_sandbox_in_browser(self):
        page, reqs = self.open("", 1280)
        page.click('[data-wp-mat="glass"]')
        self.assertEqual(page.get_attribute("#webPetWrap", "data-material"), "glass")
        page.click('[data-wp-color="orange"]')
        self.assertEqual(page.get_attribute("#webPetWrap", "data-color"), "orange")
        page.click("#webPetWrap")
        self.assertEqual(page.get_attribute("#webPetWrap", "data-action"), "press")
        self.assertTrue(all(u.startswith(self.base) for u in reqs))

        page2, reqs2 = self.open("pro/", 1280)
        page2.fill("#sandboxSearchInput", "whiteboard OCR")
        self.assertIn("IMG_4092_whiteboard_scan.png", page2.inner_text("#sandboxResults"))
        page2.click("#sandboxTabTidy")
        page2.click("#sandboxApproveBtn")
        self.assertIn("Journal V2 committed", page2.inner_text("#sandboxTidyStatus"))
        page2.click("#sandboxUndoBtn")
        self.assertIn("Undone", page2.inner_text("#sandboxTidyStatus"))
        self.assertTrue(all(u.startswith(self.base) for u in reqs2))


class _QuietHandler(http.server.SimpleHTTPRequestHandler):
    def log_message(self, *args):
        pass


if __name__ == "__main__":
    unittest.main()
