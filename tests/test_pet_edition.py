"""V1 꾸미기 에디션: 펫·재질·색·표정·모션만 열리고, 파일·기록·연결 기능은 서버가 막는다."""
import os

os.environ.setdefault("RO_LANG", "source")  # 화면 문구는 번역 전 원문으로 검사한다
import json
import tempfile
import unittest
import urllib.error
import urllib.request

from ro import pet


def _post(server, token, path, body):
    req = urllib.request.Request(
        f"http://127.0.0.1:{server.server_address[1]}{path}", data=json.dumps(body).encode(),
        headers={"X-Ro-Token": token, "Content-Type": "application/json"})
    try:
        with urllib.request.urlopen(req, timeout=5) as r:
            return r.status, json.loads(r.read())
    except urllib.error.HTTPError as e:
        return e.code, json.loads(e.read())


class MiniEditionTest(unittest.TestCase):
    def setUp(self):
        d = tempfile.mkdtemp(prefix="ro-edition-")
        self.rt = pet.PetRuntime(home=d, log_dir=d, edition="mini")
        self.server = pet.start_server(self.rt)
        self.addCleanup(self.server.server_close)
        self.addCleanup(self.server.shutdown)

    def test_function_endpoints_are_closed(self):
        for path in ("/api/find", "/api/organize/scan", "/api/capture", "/api/engines", "/api/handoff/plan",
                     "/api/write_gate", "/api/focus", "/api/activity"):
            status, body = _post(self.server, self.rt.token, path, {})
            self.assertEqual(status, 403, path)
            self.assertFalse(body["ok"])

    def test_look_and_motion_endpoints_stay_open(self):
        self.assertEqual(_post(self.server, self.rt.token, "/api/prefs", {"material": "glass"})[0], 200)
        self.assertEqual(_post(self.server, self.rt.token, "/api/action", {"action": "breathe"})[0], 200)

    def test_page_marks_edition_and_hides_function_ui(self):
        html = pet.render_html("t", {}, "mini")
        self.assertIn('class="material-clay edition-mini"', html)
        self.assertIn("body.edition-mini .pro-only", html)
        self.assertNotIn("__RO_EDITION__", html)
        self.assertIn('edition-pro', pet.render_html("t", {}, "pro"))

    def test_default_edition_is_design_and_env_can_open_full(self):
        from unittest import mock
        with mock.patch.dict("os.environ", {}, clear=False) as env:
            env.pop("RO_EDITION", None)
            self.assertEqual(pet.default_edition(), "mini")
        with mock.patch.dict("os.environ", {"RO_EDITION": "pro"}):
            self.assertEqual(pet.default_edition(), "pro")
        with mock.patch.dict("os.environ", {"RO_EDITION": "bogus"}):
            self.assertEqual(pet.default_edition(), "mini")

    def test_visible_design_copy_is_english(self):
        html = pet.render_html("t", {}, "mini")
        for label in ("Style", "Material", "ro color", "Wander", "Expression", "Motion", "Clay", "Glass"):
            self.assertIn(label, html)
        # 꾸미기 화면(상단 바 + 스타일 탭)에는 한글이 남지 않는다. 기능 탭(V2)은 숨겨 둔 채 아직 한글이다.
        import re
        top = html[html.index('id="bubbleTop"'):html.index('id="paneHome"')]
        style = html[html.index('id="paneSettings"'):html.index('id="writeCard"')]
        pet_ui = html[html.index('id="petWrap"'):html.index("<script>")]
        for part in (top, style, pet_ui):
            self.assertIsNone(re.search("[가-힣]", re.sub(r"<!--.*?-->", "", part, flags=re.S)))


if __name__ == "__main__":
    unittest.main()
