import os
import stat
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from ro import harden, log

FAKE_TOKEN = "ghp" + "_" + "abcdefghijklmnopqrstuvwxyz"  # 가짜 값. 훅이 잡지 않게 나눠 둔다


class HardenTest(unittest.TestCase):
    def test_eval_all_pass(self):
        self.assertEqual([n for n, ok in harden.evaluate() if not ok], [])

    def test_audit_finds_and_fixes_permissions(self):
        with tempfile.TemporaryDirectory() as h:
            log.append("t", "s", log_dir=h)
            f = next(Path(h).glob("*.jsonl"))
            os.chmod(f, 0o644)
            findings, _ = harden.audit(h)
            self.assertTrue(any("권한" in x for x in findings))
            _, fixed = harden.audit(h, fix=True)
            self.assertTrue(fixed)
            self.assertEqual(stat.S_IMODE(f.stat().st_mode), 0o600)
            self.assertEqual(harden.audit(h)[0], [])

    def test_audit_skips_files_that_vanish_mid_walk(self):
        """도는 사이에 사라진 임시·잠금 파일 때문에 펫 상태 조회(/api/state)가 500을 내지 않는다."""
        with tempfile.TemporaryDirectory() as h:
            os.chmod(h, 0o700)
            gone = [(Path(h), True), (Path(h) / "config.json.tmp", False), (Path(h) / "gone.jsonl", False)]
            with mock.patch.object(harden, "_walk", return_value=gone):
                self.assertEqual(harden.audit(h), ([], []))

    def test_audit_detects_secret_in_data(self):
        with tempfile.TemporaryDirectory() as h:
            p = Path(h) / "x.json"
            p.write_text('{"k": "ghp_abcdefghijklmnopqrstuvwxyz"}')
            os.chmod(p, 0o600)
            self.assertTrue(any("비밀" in x for x in harden.audit(h)[0]))

    def test_audit_reads_only_the_appended_tail_of_jsonl(self):
        fake = FAKE_TOKEN
        with tempfile.TemporaryDirectory() as h:
            os.chmod(h, 0o700)
            p = Path(h) / "log.jsonl"
            p.write_text('{"a": 1}\n' * 1000)
            os.chmod(p, 0o600)
            self.assertEqual(harden.audit(h)[0], [])
            reads = []
            real_open = open

            def spy(f, mode="r", *a, **k):
                fh = real_open(f, mode, *a, **k)
                if str(f) == str(p):
                    real_seek = fh.seek
                    fh.seek = lambda off, *x: reads.append(off) or real_seek(off, *x)
                return fh
            with real_open(p, "a") as f:
                f.write('{"k": "%s"}\nbroken\n' % fake)
            with mock.patch("builtins.open", spy):
                findings = harden.audit(h)[0]
            self.assertEqual(reads, [9000])                 # 앞 1000줄은 다시 읽지 않는다
            self.assertTrue(any("비밀" in x for x in findings))
            self.assertTrue(any("손상된 줄 1개(첫 줄 1002)" in x for x in findings))

    def test_audit_rescans_rewritten_file_and_flags_unfinished_last_line_without_caching_it(self):
        with tempfile.TemporaryDirectory() as h:
            os.chmod(h, 0o700)
            p = Path(h) / "log.jsonl"
            p.write_text('{"a": 1}\n{"b":')
            os.chmod(p, 0o600)
            self.assertTrue(any("손상된 줄" in x for x in harden.audit(h)[0]))
            with open(p, "a") as f:
                f.write(' 2}\n')                            # 쓰던 줄이 끝났다
            self.assertEqual(harden.audit(h)[0], [])
            tmp = Path(h) / "new"
            tmp.write_text('{"k": "%s"}\n' % FAKE_TOKEN)
            os.chmod(tmp, 0o600)
            os.replace(tmp, p)                               # 새 inode: 처음부터 다시 본다
            self.assertTrue(any("비밀" in x for x in harden.audit(h)[0]))

    def test_new_data_dirs_are_private(self):
        with tempfile.TemporaryDirectory() as h:
            log.append("t", "s", log_dir=Path(h) / ".ro" / "log")
            self.assertEqual(harden.audit(Path(h) / ".ro")[0], [])

    def test_network_check_catches_each_way_out_and_allows_local(self):
        with tempfile.TemporaryDirectory() as d:
            ok = Path(d) / "ok.py"
            ok.write_text("from urllib.parse import urlparse\nfrom http.server import HTTPServer\n"
                          "URL = 'http://127.0.0.1:8765/'\nHOST = 'http://localhost:9/'\n# https://example.com 주석\n")
            self.assertEqual(harden.network_offenders(d), [])
            bad = {"import urllib.request": "import urllib.request",
                   "from http import client": "import http.client",
                   "import socket as s": "import socket",
                   "subprocess.run(['curl', 'x'])": "실행 curl",
                   "X = 'https://example.com/upload'": "원격 주소"}
            for code, reason in bad.items():
                (Path(d) / "bad.py").write_text(code + "\n")
                self.assertTrue(any(reason in f for f in harden.network_offenders(d)), code)
            (Path(d) / "bad.py").unlink()
            # 하위 폴더(ro/hooks 등)와 Swift 호스트도 검사 범위다(2026-10-30 재감사: 최상위 *.py만 보던 빈틈)
            (Path(d) / "hooks").mkdir()
            (Path(d) / "hooks" / "h.py").write_text("import socket\n")
            self.assertTrue(any("h.py" in f for f in harden.network_offenders(d)))
            (Path(d) / "hooks" / "h.py").unlink()
            (Path(d) / "host.swift").write_text('let u = "http://127.0.0.1:8765/"\n')
            self.assertEqual(harden.network_offenders(d), [])
            (Path(d) / "host.swift").write_text("let s = URLSession.shared\n")
            self.assertTrue(any("host.swift" in f for f in harden.network_offenders(d)))

    def test_eval_fails_when_protection_removed(self):
        # 회귀: 보호 장치를 꺼도 PASS가 나오던 공허한 검사
        def failed(name):
            return dict(harden.evaluate())[name] is False

        with mock.patch("ro.mapper.is_secret", return_value=False):
            self.assertTrue(failed("Map은 비밀 파일 제외"))
        with mock.patch("ro.harden.network_offenders", return_value=["x.py:1 import socket"]):
            self.assertTrue(failed("기기 밖으로 보내는 코드 없음(네트워크 모듈·명령·원격 주소, pro 라이선스 받기 한 곳 제외)"))
        with mock.patch("ro.harden.license_net_scoped", return_value=["설치 토큰 말고 다른 값을 보냄"]):
            self.assertTrue(failed("pro 라이선스 받기는 발급기 한 곳에 설치 토큰만 보냄"))


if __name__ == "__main__":
    unittest.main()
