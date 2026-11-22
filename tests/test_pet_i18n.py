"""화면 언어: 기본은 영어, 설정(⋯ 메뉴의 Language)에서 한국어로 바꾼다. 원문은 그대로 두고 보일 때 번역한다."""
import os

os.environ.setdefault("RO_LANG", "source")  # 화면 문구는 번역 전 원문으로 검사한다
import json
import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from ro import pet

I18N = (Path(pet.__file__).with_name("pet_ui") / "i18n.js").read_text(encoding="utf-8")
SWIFT = Path(pet.__file__).with_name("pet_mac.swift").read_text(encoding="utf-8")


def run_text(lang, samples):
    """i18n.js의 번역 함수만 node에서 돌린다(DOM은 빈 껍데기)."""
    script = """
const document = {documentElement: {}, body: {nodeType: 1, tagName: 'BODY', matches: () => false,
  getAttribute: () => null, childNodes: []}};
class MutationObserver { observe() {} }
SOURCE
console.log(JSON.stringify(SAMPLES.map(s => RoI18n.text(s))));
""".replace("SOURCE", I18N.replace("__RO_LANG__", lang)).replace("SAMPLES", json.dumps(samples, ensure_ascii=False))
    result = subprocess.run(["node", "-e", script], capture_output=True, text=True, timeout=10)
    assert result.returncode == 0, result.stderr
    return json.loads(result.stdout)


class LangPrefTest(unittest.TestCase):
    def test_default_is_english_and_env_can_pin_source(self):
        with mock.patch.dict(os.environ, {}, clear=False):
            os.environ.pop("RO_LANG", None)
            self.assertEqual(pet.default_lang(), "en")
            self.assertIn('const RO_LANG = "en";', pet.render_html("t", {}, "pro"))
        with mock.patch.dict(os.environ, {"RO_LANG": "source"}):
            self.assertIn('const RO_LANG = "source";', pet.render_html("t", {}, "pro"))
        with mock.patch.dict(os.environ, {"RO_LANG": "nonsense"}):
            self.assertEqual(pet.default_lang(), "en")

    def test_saved_language_wins_and_only_known_values_save(self):
        with tempfile.TemporaryDirectory() as d:
            rt = pet.PetRuntime(home=d, log_dir=d, map_path=str(Path(d) / "map.json"))
            self.assertTrue(rt.set_prefs({"lang": "ko"})["ok"])
            self.assertIn('const RO_LANG = "ko";', pet.render_html(rt.token, rt.prefs(), "pro"))
            self.assertFalse(rt.set_prefs({"lang": "source"})["ok"])   # 원문 모드는 설정으로 고를 수 없다
            self.assertEqual(rt.prefs()["lang"], "ko")

    def test_language_is_chosen_from_the_host_menu_not_the_panel(self):
        self.assertIn('for (label, value) in [("English", "en"), ("한국어", "ko")]', SWIFT)
        self.assertIn('item.representedObject = ["lang", value]', SWIFT)
        self.assertIn('if (key === "lang") {', pet.PET_HTML)
        html = (Path(pet.__file__).with_name("pet_ui") / "pet.html").read_text(encoding="utf-8")
        self.assertNotIn("Language", html)   # 상태창 본문에는 언어 고르기를 두지 않는다


@unittest.skipUnless(shutil.which("node"), "node 필요")
class TranslateTest(unittest.TestCase):
    def test_korean_source_reads_in_english(self):
        got = run_text("en", ["확인할 일", "  오늘 3건 기록했어요.  ", "문서 2개", "문서 2 · 보관함 1", "되돌리기 · 11/11 15:50 3개",
                              "파일 정리: 문서 2건을 ~/Documents/정리됨/문서로 옮기고 이름을 바꿉니다.", "Settings, 연결할 항목 2개"])
        self.assertEqual(got, ["To review", "  3 logged today.  ", "Docs · 2", "Docs 2 · Holding 1", "Undo · 11/11 15:50 (3)",
                               "Tidy: move 2 in Docs to ~/Documents/정리됨/문서 and rename them.", "Settings, 2 to connect"])

    def test_pro_card_and_learned_screen_read_in_english(self):
        """RO-AUD-108: ro pro 확인 카드·배운 것 화면의 말(정적·동적)이 영어 모드에서 한국어로 남지 않는다."""
        js = (Path(pet.__file__).with_name("pet_ui") / "pet.js").read_text(encoding="utf-8")
        import re
        tables = re.search(r"const STAGE_OPS = \{[^}]*\};\s*async function stageCard[\s\S]*?\n}\n", js).group(0)
        tables += re.search(r"const LEARNED_STATE[\s\S]*?\nasync function learnedCard[\s\S]*?\n}\n", js).group(0)
        static = sorted({s for s in re.findall(r'"([^"\n$`]*[가-힣][^"\n$`]*)"', tables)})
        dynamic = ["확실한 것 3개", "확실한 것 3개 (선택됨)", "아마도요 2개 — 직접 골라 주세요", "옮김 2건 · 사본 내보냄 0건 · 건너뜀 1건",
                   "되돌렸어요 · 파일 2개 제자리로 · 바뀐 것 1개는 그대로", "ro가 배운 것 · 학습 켜짐 · 먼저 알림 꺼짐",
                   "먼저 알림 30일: 12번 · 도움 40% · 끄기 10% · 통과 · 1단계로 낮춘 유형 찾기 헤맴, 옛 판본",
                   "찾기 헤맴 다시 켜기", "4일", "설치 파일 격리 · 1개 · 2.0MB", "old-app · 120일 안 바뀜 · 다시 만들 수 있음",
                   "Pages 설치됨", "200일 안 씀 · iCloud에 남고 이 Mac 사본만 내보냄", "지난번에 끝나지 않은 정리 2건을 되돌렸어요",
                   "학습 켜짐 · 먼저 알림 꺼짐 · 손쉬운 사용 권한 필요",
                   "Linear 앱이 설치돼 있어요 · Linear-1.20.dmg 남음",
                   "시동 디스크 남은 공간 7.4GB",
                   "다운로드에 새 파일 4개가 들어왔어요",
                   "BrandAssets.zip 압축이 이미 풀려 있어요",
                   "다운로드에 중복 사본 2개가 있어요",
                   "Claude에서 Codex(으)로 도구를 바꿨어요",
                   "2분 동안 폴더를 5번 오가셨어요",
                   "같은 폴더에 더 새 판이 있어요 · Deck_v2.pdf"]
        samples = static + dynamic
        left = [(s, t) for s, t in zip(samples, run_text("en", samples)) if any("가" <= c <= "힣" for c in t)]
        self.assertGreater(len(static), 15)
        self.assertEqual(left, [])

    def test_what_the_user_wrote_is_left_alone(self):
        # 표에 없는 말, 모르는 이름이 낀 '개' 문장은 사용자가 쓴 글일 수 있다
        samples = ["회의록 정리 끝냄", "보고서 3개", "스케치 안 확정함"]
        self.assertEqual(run_text("en", samples), samples)

    def test_english_source_reads_in_korean_and_source_mode_changes_nothing(self):
        self.assertEqual(run_text("ko", ["Settings", "Turn on focus mode", "확인할 일", "Evening · 2"]),
                         ["설정", "집중 모드 켜기", "확인할 일", "저녁 · 2"])
        samples = ["Settings", "확인할 일"]
        self.assertEqual(run_text("source", samples), samples)


class HostTest(unittest.TestCase):
    def test_mini_panel_does_not_take_focus(self):
        fn = SWIFT.split("private func bringPanelForward()")[1].split("\n    }\n")[0]
        self.assertLess(fn.index("if miniEdition {"), fn.index("NSApp.activate"))
        self.assertIn("panel.orderFrontRegardless()", fn)

    def test_open_at_login_only_inside_the_app_bundle(self):
        self.assertIn("import ServiceManagement", SWIFT)
        self.assertIn('if #available(macOS 13.0, *), Bundle.main.bundleURL.pathExtension == "app" {', SWIFT)
        self.assertIn("try SMAppService.mainApp.register()", SWIFT)

    def test_transparent_margin_lets_clicks_through_only_after_the_page_reports(self):
        fn = SWIFT.split("private func updateClickThrough()")[1].split("\n    }\n")[0]
        self.assertIn("guard hitReady, !isDragging, panel.isVisible else {", fn)   # 자리를 모르면 클릭을 버리지 않는다
        self.assertIn('notifyHost({ type: "hit"', pet.PET_HTML)


if __name__ == "__main__":
    unittest.main()
