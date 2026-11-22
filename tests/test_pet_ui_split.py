"""디자인/기능 분리 경계. 화면은 ro/pet_ui/, 기능은 ro/pet.py에만 둔다."""
import os

os.environ.setdefault("RO_LANG", "source")  # 화면 문구는 번역 전 원문으로 검사한다
import re
import unittest
from pathlib import Path

from ro import pet

UI = Path(pet.__file__).with_name("pet_ui")


class PetUiSplitTest(unittest.TestCase):
    def test_pet_py_holds_no_markup(self):
        source = Path(pet.__file__).read_text(encoding="utf-8")
        for tag in ("<style", "<script", "<!DOCTYPE", "<body"):
            self.assertNotIn(tag, source)

    def test_template_has_one_slot_each(self):
        tpl = (UI / "pet.html").read_text(encoding="utf-8")
        self.assertEqual(tpl.count("__RO_CSS__"), 1)
        self.assertEqual(tpl.count("__RO_JS__"), 1)
        for name in ("pet.css", "pet.js"):
            body = (UI / name).read_text(encoding="utf-8")
            self.assertNotRegex(body, r"__RO_(CSS|JS)__")
            self.assertNotIn("</style>" if name == "pet.css" else "</script>", body)

    def test_assembled_page_keeps_bridge_slots(self):
        # 기능 쪽(render_html)이 채우는 자리: 토큰·설정·에디션
        for slot in ("__RO_TOKEN__", "__RO_PREFS__", "__RO_EDITION__"):
            self.assertIn(slot, pet.PET_HTML)
        html = pet.render_html("t", {})
        self.assertNotRegex(html, r"__RO_[A-Z_]+__")
        self.assertEqual(len(re.findall(r"<style>", html)), 1)
        self.assertEqual(len(re.findall(r"<script>", html)), 1)


if __name__ == "__main__":
    unittest.main()
