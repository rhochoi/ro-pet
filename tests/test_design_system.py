"""디자인 시스템 린트(docs/DESIGN-SYSTEM.md). 펫 화면 CSS가 디자인 철학 v2의 규칙에서 멀어지지 않게 막는다.

규칙은 래칫이다: 지금 남아 있는 예외는 허용하되 늘어나면 실패한다. 줄였으면 상한도 같이 내린다.
"""
import os

os.environ.setdefault("RO_LANG", "source")  # 화면 문구는 번역 전 원문으로 검사한다
import re
import unittest

from ro import pet

CSS = "\n".join(re.findall(r"<style[^>]*>(.*?)</style>", pet.PET_HTML, re.S))

# 목표 값(DESIGN-SYSTEM.md 2절). 이 밖의 값은 정리 대상이다.
RADIUS_TARGET = {"999px", "50%", "12px", "6px", "0", "inherit", "999px 999px 0 0"}
FONT_TARGET = {"11px", "13px", "15px", "20px"}
# 래칫 상한(2026-11-07 상태창 재설계 후 측정값). 정리하면서 내린다. 올리지 않는다.
RADIUS_OFF_TARGET_MAX = 2
FONT_OFF_TARGET_MAX = 0
# 주황 점은 사람이 판단할 예외 표시에만(색감 A, 2026-11-01): 확인할 일 점, 기록 정리의 '확인 필요' 점.
# ro 몸통의 주황은 --ro-orange로 따로 둔다(사용자 결정, 2026-11-07)
ACCENT_ALLOWED = {".attn-dot", ".rec-org-dot"}


def _values(prop):
    return [v.replace("!important", "").strip() for v in re.findall(rf"{prop}:\s*([^;]+);", CSS)]


def _block(selector):
    m = re.search(re.escape(selector) + r"\s*\{([^}]*)\}", CSS)
    return dict(re.findall(r"(--[a-z0-9-]+):\s*([^;]+);", m.group(1)))


def _luminance(hex_):
    c = [int(hex_[i:i + 2], 16) / 255 for i in (1, 3, 5)]
    c = [x / 12.92 if x <= 0.04045 else ((x + 0.055) / 1.055) ** 2.4 for x in c]
    return 0.2126 * c[0] + 0.7152 * c[1] + 0.0722 * c[2]


def _themes():
    """CSS처럼 푼다: :root의 var()는 :root 값으로 계산된 채 상속되고, 어두운 면 블록은 자기가 다시 선언한 것만 바꾼다."""
    light = _block(":root")
    resolve = lambda t, k: t[k] if t[k].startswith("#") else resolve(t, t[k][4:-1])
    light = {k: resolve(light, k) for k in light if not light[k].startswith("rgba")}
    dark_block = _block("body.theme-chalk")
    dark = {**light, **dark_block}
    dark = {k: resolve(dark, k) if k in dark_block else v for k, v in dark.items() if not v.startswith("rgba")}
    return light, dark


def contrast(a, b):
    la, lb = sorted((_luminance(a), _luminance(b)), reverse=True)
    return (la + 0.05) / (lb + 0.05)


class DesignLintTest(unittest.TestCase):
    def test_radius_off_target_does_not_grow(self):
        off = [v for v in _values("border-radius") if v not in RADIUS_TARGET]
        self.assertLessEqual(len(off), RADIUS_OFF_TARGET_MAX,
                             f"모서리는 999px·12px·6px만 쓴다(DESIGN-SYSTEM.md). 새로 늘어난 값: {sorted(set(off))}")

    def test_font_size_off_target_does_not_grow(self):
        off = [v for v in _values("font-size") if v not in FONT_TARGET]
        self.assertLessEqual(len(off), FONT_OFF_TARGET_MAX,
                             f"글자 크기는 11·13·15·20px만 쓴다. 목표 밖 값: {sorted(set(off))}")

    def test_accent_only_marks_exceptions(self):
        # 원칙 2·색감 A: 주황은 펼쳐진 예외(사람이 판단할 곳)에만. 버튼·포커스·선택·막대는 잉크나 밤색
        rules = re.findall(r"([^{}]+)\{([^}]*)\}", CSS)
        users = {s.strip().split("\n")[-1].strip() for s, body in rules if "var(--accent)" in body}
        self.assertLessEqual(users, ACCENT_ALLOWED, f"주황을 새로 쓴 곳: {sorted(users - ACCENT_ALLOWED)}")

    def test_selected_and_inverse_tokens_are_legible(self):
        light, dark = _themes()
        resolve = lambda t, k: t[k]
        for name, theme in (("밝은 면", light), ("어두운 면", dark)):
            with self.subTest(theme=name):
                # '선택됨' 면(켜진 토글·강조 테두리)은 잉크: 비텍스트 대비 3:1
                self.assertGreaterEqual(contrast(resolve(theme, "--selected"), resolve(theme, "--panel-bg")), 3)
                # 잉크 버튼 위 글자(패널 바탕색)
                self.assertGreaterEqual(contrast(resolve(theme, "--panel-bg"), resolve(theme, "--panel-fg")), 4.5)
        # 스테이징 바탕(분필) 위 주황 글자
        self.assertGreaterEqual(contrast(resolve(light, "--accent-text"), resolve(light, "--chalk-soft")), 4.5)

    def test_text_tokens_meet_contrast_in_both_themes(self):
        light, dark = _themes()
        resolve = lambda t, k: t[k]
        pairs = [("--panel-fg", "--panel-bg"), ("--muted", "--panel-bg"), ("--muted", "--panel-soft"),
                 ("--accent-text", "--panel-bg"), ("--bubble-fg", "--bubble-fill")]
        for name, theme in (("밝은 면", light), ("어두운 면", dark)):
            for fg, bg in pairs:
                with self.subTest(theme=name, fg=fg, bg=bg):
                    ratio = contrast(resolve(theme, fg), resolve(theme, bg))
                    self.assertGreaterEqual(ratio, 4.5, f"{name} {fg} on {bg} = {ratio:.2f}")

    def test_ro_orange_is_softer_than_accent_and_keeps_ink_eyes(self):
        light, _ = _themes()
        self.assertEqual(light["--ro-orange"], "#F3874E")
        self.assertGreaterEqual(contrast(light["--ro-orange"], light["--ink"]), 4.5)
        self.assertGreater(contrast(light["--ro-orange"], light["--ink"]), contrast(light["--accent"], light["--ink"]))

    def test_text_on_accent_is_ink_not_white(self):
        # 주황 위 흰 글자는 3.3:1로 본문 기준 미달, 잉크는 5.3:1
        self.assertLess(contrast("#FFFFFF", "#FF4B1F"), 4.5)
        self.assertGreaterEqual(contrast("#1A1917", "#FF4B1F"), 4.5)

    def test_reduced_motion_is_respected(self):
        self.assertIn("prefers-reduced-motion", CSS)


if __name__ == "__main__":
    unittest.main()
