"""2026-11-15 감사 결함(RO-AUD-001..027) 보강 회귀 테스트."""
import http.client
import io
import json
import os
import re
import runpy
import shutil
import subprocess
import sys
import tempfile
import time
import unittest
from contextlib import redirect_stderr
from pathlib import Path
from unittest import mock
from urllib.error import HTTPError
from urllib.request import Request, urlopen

os.environ.setdefault("RO_LANG", "source")

from ro import cli, log, mapper, organize, pet, records
from tests._pet_browser import launch_chromium

REPO = Path(__file__).resolve().parent.parent
UI_DIR = REPO / "ro" / "pet_ui"


def _node_i18n(lang, texts):
    src = (UI_DIR / "i18n.js").read_text(encoding="utf-8")
    src = src.replace('"__RO_LANG__"', json.dumps(lang), 1).replace("\nRoI18n.start();", "")
    script = (
        "const document = { documentElement: {}, body: null };\n"
        + src
        + f"\nconsole.log(JSON.stringify({json.dumps(texts)}.map(s => RoI18n.text(s))));\n"
    )
    res = subprocess.run(["node", "-e", script], capture_output=True, text=True, timeout=15, check=True)
    return json.loads(res.stdout)


class PetBrowserHelperTest(unittest.TestCase):
    def test_launch_chromium_skips_missing_browser_only_outside_ci(self):
        pw = mock.Mock()
        pw.chromium.launch.side_effect = RuntimeError("BrowserType.launch: Executable doesn't exist at /none")
        with mock.patch.dict(os.environ, {}, clear=False):
            os.environ.pop("CI", None)
            with self.assertRaises(unittest.SkipTest):
                launch_chromium(pw)

        with mock.patch.dict(os.environ, {"CI": "1"}):
            with self.assertRaises(RuntimeError):
                launch_chromium(pw)

    def test_launch_chromium_reraises_unrelated_error_even_outside_ci(self):
        pw = mock.Mock()
        pw.chromium.launch.side_effect = RuntimeError("unexpected launch failure")
        with mock.patch.dict(os.environ, {}, clear=False):
            os.environ.pop("CI", None)
            with self.assertRaises(RuntimeError):
                launch_chromium(pw)


class MiniIsolationAndSummaryTest(unittest.TestCase):
    def test_mini_snapshot_and_state_endpoint_expose_no_user_data(self):
        with tempfile.TemporaryDirectory() as d, mock.patch.dict(os.environ, {"HOME": d}):
            home = Path(d)
            mp = str(home / "map.json")
            log.append("note", "비밀 사용자 메모", log_dir=d)
            mapper.save_map(
                {"projects": [{"name": "secret-proj", "path": d, "languages": ["python"], "git": None, "summary": {}}],
                 "tools": {}},
                mp,
            )
            src_dir = home / "src"
            src_dir.mkdir()
            (src_dir / "doc.txt").write_text("hello", encoding="utf-8")
            plan = organize.scan(root=src_dir, dest_root=home / "out", now=time.time() + 3600)
            organize.save_plan(plan, home=home)

            rt = pet.PetRuntime(home=d, log_dir=d, map_path=mp, edition="mini")
            with mock.patch.object(mapper, "load_map", side_effect=AssertionError("mini must not read map")) as m_map, \
                 mock.patch.object(rt, "organize_summary", side_effect=AssertionError("mini must not read organize")):
                snap = rt.snapshot()
            m_map.assert_not_called()
            self.assertEqual(rt.edition, "mini")
            self.assertEqual(snap["mood"], "idle")
            self.assertIn(snap["ambient"]["band"], ("Morning", "Afternoon", "Evening"))
            self.assertEqual(snap["ambient"]["label"], snap["ambient"]["band"])
            self.assertFalse(snap["ambient"]["focus"])
            self.assertEqual(snap["ambient"]["held"], 0)
            self.assertFalse(snap["ambient"]["attention"])
            self.assertFalse(snap.get("projects"))
            self.assertEqual(snap["timeline"], [])
            self.assertEqual(snap["counts"], {"today_events": 0, "today_records": 0, "projects": 0, "audit_findings": 0})
            self.assertFalse(snap.get("organize"))
            dumped = json.dumps(snap, ensure_ascii=False)
            self.assertNotIn("secret-proj", dumped)
            self.assertNotIn("비밀 사용자 메모", dumped)

            server = pet.start_server(rt)
            try:
                req = Request(f"http://127.0.0.1:{server.server_address[1]}/api/state",
                              headers={"X-Ro-Token": rt.token})
                remote = json.loads(urlopen(req, timeout=5).read())
                self.assertFalse(remote.get("projects"))
                self.assertEqual(remote["timeline"], [])
                self.assertNotIn("secret-proj", json.dumps(remote, ensure_ascii=False))
            finally:
                server.shutdown()
                server.server_close()

    def test_organize_summary_counts_review_quarantine_items(self):
        with tempfile.TemporaryDirectory() as d, mock.patch.dict(os.environ, {"HOME": d}):
            home = Path(d)
            src = home / "dl"
            src.mkdir()
            (src / "a.txt").write_bytes(b"same-data" * 300)
            (src / "a (1).txt").write_bytes(b"same-data" * 300)
            (src / "keep.txt").write_bytes(b"keep-data" * 200)
            plan = organize.scan(root=src, dest_root=home / "organized", now=time.time() + 3600)
            self.assertTrue(any(i.get("action") == "quarantine" for i in plan["items"]), plan["items"])
            for it in plan["items"]:
                if it.get("action") == "quarantine":
                    it["review"] = True
                if it["path"].endswith("keep.txt"):
                    it["action"] = "keep"
                    it["review"] = True
            organize.save_plan(plan, home=home)

            rt = pet.PetRuntime(home=d, log_dir=d, map_path=str(home / "map.json"))
            summary = rt.organize_summary()
            self.assertIsNotNone(summary)
            self.assertGreaterEqual(summary["review"], 1)
            self.assertEqual(
                summary["review"],
                sum(1 for i in plan["items"] if i["review"] and i.get("action", "move") != "keep"),
            )


class PetHttpValidationAndSizeTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.home = Path(self.tmp.name)
        mp = str(self.home / "map.json")
        mapper.save_map({"projects": [], "tools": {}}, mp)
        self.rt = pet.PetRuntime(home=self.tmp.name, log_dir=self.tmp.name, map_path=mp)
        self.server = pet.start_server(self.rt)
        self.port = self.server.server_address[1]

    def tearDown(self):
        self.server.shutdown()
        self.server.server_close()
        self.tmp.cleanup()

    def _post_raw(self, path, raw_body, headers):
        conn = http.client.HTTPConnection("127.0.0.1", self.port, timeout=5)
        try:
            conn.request("POST", path, body=raw_body, headers=headers)
            resp = conn.getresponse()
            return resp.status, json.loads(resp.read().decode("utf-8"))
        finally:
            conn.close()

    def _post_json(self, path, body):
        req = Request(
            f"http://127.0.0.1:{self.port}{path}",
            data=json.dumps(body).encode("utf-8"),
            headers={"X-Ro-Token": self.rt.token, "Content-Type": "application/json"},
        )
        try:
            with urlopen(req, timeout=5) as r:
                return r.status, json.loads(r.read().decode("utf-8"))
        except HTTPError as exc:
            return exc.code, json.loads(exc.read().decode("utf-8"))

    def test_invalid_content_length_and_json_shapes_return_400(self):
        for bad_len in ("-5", "abc"):
            status, payload = self._post_raw(
                "/api/prefs",
                None,
                {"X-Ro-Token": self.rt.token, "Content-Length": bad_len},
            )
            self.assertEqual(status, 400)
            self.assertFalse(payload["ok"])

        status, payload = self._post_json("/api/prefs", [])
        self.assertEqual(status, 400)
        self.assertEqual(payload, {"ok": False, "error": "A JSON object is required."})

        status, payload = self._post_json("/api/focus", {"on": "yes"})
        self.assertEqual(status, 400)
        self.assertEqual(payload, {"ok": False, "error": "on must be true or false."})
        self.assertFalse(self.rt.snapshot()["ambient"]["focus"])

        for path, body in (
            ("/api/prefs", {}),
            ("/api/action", {}),
            ("/api/find/signals", {}),
            ("/api/activity", {"action": "nope"}),
        ):
            code, err = self._post_json(path, body)
            self.assertEqual(code, 400, (path, body, err))
            self.assertFalse(err["ok"])

    def test_pro_snapshot_hides_pet_error_events(self):
        log.append("note", "정상 기록", log_dir=self.tmp.name)
        log.append("pet_error", "내부 오류", log_dir=self.tmp.name)
        snap = self.rt.snapshot()
        self.assertEqual(snap["counts"]["today_events"], 1)
        self.assertEqual([e["kind"] for e in snap["timeline"]], ["note"])
        self.assertNotIn("pet_error", json.dumps(snap, ensure_ascii=False))

    def test_size_pref_persists_and_ui_scales_bubbles_and_chips(self):
        self.rt.set_prefs({"size": "big"})
        html = urlopen(f"http://127.0.0.1:{self.port}/", timeout=5).read().decode("utf-8")
        m = re.search(r"const INITIAL_PREFS = (.*);", html)
        self.assertIsNotNone(m)
        self.assertEqual(json.loads(m.group(1))["size"], "big")

        js = (UI_DIR / "pet.js").read_text(encoding="utf-8")
        css = (UI_DIR / "pet.css").read_text(encoding="utf-8")
        self.assertIn("if (!isNativeHost && PET_SCALES[INITIAL_PREFS.size]) window.setPetSize(INITIAL_PREFS.size);", js)
        self.assertIn('"aria-label": label', js)
        self.assertRegex(css, r"\.bubble\s*\{[^}]*var\(--pet-scale,\s*1\)")
        self.assertRegex(css, r"body\.edition-mini\s*\.bubble\s*\{[^}]*var\(--pet-scale,\s*1\)")


class I18nRecordsAndCliRegressionTest(unittest.TestCase):
    @unittest.skipUnless(shutil.which("node"), "node 필요")
    def test_i18n_translations_and_fmt_bytes_zero(self):
        ko_bands = _node_i18n("ko", ["Morning", "Afternoon", "Evening"])
        self.assertEqual(ko_bands, ["오전", "오후", "저녁"])

        en_out = _node_i18n(
            "en",
            [
                "풀린 압축 1건 격리 (되돌리기 가능, 삭제 아님)",
                "풀린 압축 2건 격리 (되돌리기 가능, 삭제 아님)",
                "중복 1개를 보관함으로(지우지 않음, 되돌리기 가능) — 승인 카드에서 한 번 더 확인합니다",
                "중복 2개를 보관함으로(지우지 않음, 되돌리기 가능) — 승인 카드에서 한 번 더 확인합니다",
                "옛 버전 1건(10KB)을 보관함(~/org)으로 옮깁니다. 지우지 않고, 되돌릴 수 있어요.",
                "옛 버전 2건(20KB)을 보관함(~/org)으로 옮깁니다. 지우지 않고, 되돌릴 수 있어요.",
                "검토가 필요한 1개는 옮기지 않아요",
                "검토가 필요한 2개는 옮기지 않아요",
                "정리안 1건",
                "정리안 2건",
                "최근 10분 안에 받거나 고친 파일 1개는 아직 쓰는 중일 수 있어 건너뛰었어요.",
                "최근 10분 안에 받거나 고친 파일 2개는 아직 쓰는 중일 수 있어 건너뛰었어요.",
                "2026-11-15 10:00에 정리한 1건을 원래 이름·위치로 되돌립니다.",
                "2026-11-15 10:00에 정리한 2건을 원래 이름·위치로 되돌립니다.",
                "이름이 '계약'으로 시작",
            ],
        )
        self.assertEqual(en_out[0], "1 unpacked archive sent to holding (can be undone, not deleted)")
        self.assertEqual(en_out[1], "2 unpacked archives sent to holding (can be undone, not deleted)")
        self.assertEqual(en_out[2], "Send 1 duplicate to holding (not deleted, can be undone). You confirm once more in the card.")
        self.assertEqual(en_out[3], "Send 2 duplicates to holding (not deleted, can be undone). You confirm once more in the card.")
        self.assertEqual(en_out[4], "Send 1 old version (10KB) to holding (~/org). Nothing is deleted, and you can undo it.")
        self.assertEqual(en_out[5], "Send 2 old versions (20KB) to holding (~/org). Nothing is deleted, and you can undo it.")
        self.assertEqual(en_out[6], "1 file needs review (won't be moved)")
        self.assertEqual(en_out[7], "2 files need review (won't be moved)")
        self.assertEqual(en_out[8], "Plan with 1 file")
        self.assertEqual(en_out[9], "Plan with 2 files")
        self.assertIn("Skipped 1 file", en_out[10])
        self.assertIn("Skipped 2 files", en_out[11])
        self.assertEqual(en_out[12], "Put the 1 file tidied at 2026-11-15 10:00 back to its original name and place.")
        self.assertEqual(en_out[13], "Put the 2 files tidied at 2026-11-15 10:00 back to their original names and places.")
        self.assertEqual(en_out[14], "Name starts with '계약'")

        js = (UI_DIR / "pet.js").read_text(encoding="utf-8")
        m = re.search(r"function fmtBytes\(n\)[\s\S]*?\n\}", js)
        self.assertIsNotNone(m)
        r = subprocess.run(
            ["node", "-e", m.group(0) + "\nconsole.log(fmtBytes(0));"],
            capture_output=True, text=True, timeout=15, check=True,
        )
        self.assertEqual(r.stdout.strip(), "0KB")

    def test_records_kind_labels_cover_all_known_kinds(self):
        for k, expected in (
            ("storage", "용량"),
            ("handoff", "인수인계"),
            ("handoff_rate", "인수인계 평가"),
        ):
            self.assertEqual(records.KIND_LABELS[k], expected)
            self.assertEqual(records.kind_label(k), expected)
        for k in ("map", "audit", "eval", "bench"):
            self.assertIn(k, records.KIND_LABELS)
            self.assertNotEqual(records.kind_label(k), "기록")

    def test_cli_validation_keyboard_interrupt_and_tilde_organize_paths(self):
        with tempfile.TemporaryDirectory() as d:
            home = Path(d)
            env = {**os.environ, "HOME": d}
            for args in (
                ["find", ""],
                ["find", "x", "--n", "0"],
                ["activity", "pause", "--minutes", "0"],
                ["activity", "pause", "--minutes", "20000"],
            ):
                r = subprocess.run(
                    [sys.executable, "-m", "ro", *args],
                    cwd=REPO, env=env, capture_output=True, text=True, timeout=30,
                )
                self.assertNotEqual(r.returncode, 0, args)

            # organize show / status 경로 ~ 단축
            src = home / "downloads"
            src.mkdir()
            sample = src / "sample.txt"
            sample.write_text("hello world", encoding="utf-8")
            old = time.time() - 3600
            os.utime(sample, (old, old))
            dest_dir = home / "organized"
            scan_r = subprocess.run(
                [sys.executable, "-m", "ro", "organize", "scan", "--root", str(src), "--dest", str(dest_dir)],
                cwd=REPO, env=env, capture_output=True, text=True, timeout=30,
            )
            self.assertEqual(scan_r.returncode, 0, scan_r.stderr)
            show_r = subprocess.run(
                [sys.executable, "-m", "ro", "organize", "show"],
                cwd=REPO, env=env, capture_output=True, text=True, timeout=30,
            )
            self.assertEqual(show_r.returncode, 0, show_r.stderr)
            self.assertIn("~/organized", show_r.stdout)
            self.assertNotIn(str(home.resolve()), show_r.stdout)

            plan_path = home / ".ro" / "cleanup" / "plan.json"
            first_id = json.loads(plan_path.read_text(encoding="utf-8"))["items"][0]["id"]
            apply_r = subprocess.run(
                [sys.executable, "-m", "ro", "organize", "apply", first_id],
                cwd=REPO, env=env, capture_output=True, text=True, timeout=30,
            )
            self.assertEqual(apply_r.returncode, 0, apply_r.stderr)
            status_r = subprocess.run(
                [sys.executable, "-m", "ro", "organize", "status"],
                cwd=REPO, env=env, capture_output=True, text=True, timeout=30,
            )
            self.assertEqual(status_r.returncode, 0, status_r.stderr)
            self.assertIn("~/", status_r.stdout)
            self.assertNotIn(str(home.resolve()), status_r.stdout)

            eval_env = {k: v for k, v in env.items() if k != "RO_EDITION"}
            eval_r = subprocess.run(
                [sys.executable, "-m", "ro", "eval"],
                cwd=REPO, env=eval_env, capture_output=True, text=True, timeout=60,
            )
            self.assertEqual(eval_r.returncode, 0, eval_r.stdout + eval_r.stderr)
            self.assertNotIn("FAIL", eval_r.stdout)

        buf = io.StringIO()
        with mock.patch("ro.cli._run", side_effect=KeyboardInterrupt), redirect_stderr(buf):
            rc = cli.main(["find", "abc"])
        self.assertEqual(rc, 130)
        self.assertIn("중단했습니다.", buf.getvalue())

        buf2 = io.StringIO()
        with mock.patch("ro.cli.main", side_effect=KeyboardInterrupt), redirect_stderr(buf2):
            with self.assertRaises(SystemExit) as ctx:
                runpy.run_module("ro.__main__", run_name="__main__")
        self.assertEqual(ctx.exception.code, 130)
        self.assertIn("중단했습니다.", buf2.getvalue())


if __name__ == "__main__":
    unittest.main()


class PetRecallTypeTest(unittest.TestCase):
    """RO-AUD-105: /api/recall에 문자열이 아닌 질문을 주면 500이 아니라 400이다."""

    def test_non_string_question_is_400(self):
        with tempfile.TemporaryDirectory() as tmp:
            rt = pet.PetRuntime(home=tmp, log_dir=tmp, map_path=str(Path(tmp) / "map.json"), edition="pro")
            srv = pet.start_server(rt)
            try:
                port = srv.server_address[1]
                for body, want in (({"question": 5}, 400), ({"question": ["a"]}, 400), ({"question": "어제 뭐 했지?"}, 200)):
                    req = Request(f"http://127.0.0.1:{port}/api/recall", data=json.dumps(body).encode(),
                                  method="POST", headers={"X-Ro-Token": rt.token})
                    try:
                        with urlopen(req) as r:
                            code = r.status
                    except HTTPError as e:
                        code = e.code
                    self.assertEqual(code, want, body)
            finally:
                srv.shutdown()
                srv.server_close()
