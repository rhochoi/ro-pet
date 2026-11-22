import os
import stat
import subprocess
import sys
import tempfile
import time
import unittest
from pathlib import Path

from ro import fsguard

ROOT = Path(__file__).resolve().parents[1]


def fake_st(flags=0, mode=stat.S_IFREG | 0o644, mtime=0):
    return os.stat_result((mode, 1, 1, 1, 0, 0, 10, mtime, mtime, mtime), {"st_flags": flags})


class FsGuardTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)

    def tearDown(self):
        self.tmp.cleanup()

    def touch(self, rel, data=b"x", age=3600):
        p = self.root / rel
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_bytes(data)
        t = time.time() - age
        os.utime(p, (t, t))
        return p

    @unittest.skipUnless(sys.platform == "darwin", "macOS 전용")
    def test_importing_ro_turns_off_materialization_in_a_fresh_process(self):
        code = "import ro, ro.fsguard as g; print(g.materialization_policy())"
        out = subprocess.run([sys.executable, "-c", code], cwd=ROOT, capture_output=True, text=True, check=True)
        self.assertEqual(out.stdout.strip(), "1")

    def test_dataless_by_flag_and_legacy_placeholder(self):
        self.assertTrue(fsguard.is_dataless("a.pdf", fake_st(fsguard.SF_DATALESS)))
        self.assertFalse(fsguard.is_dataless("a.pdf", fake_st(0)))
        self.assertTrue(fsguard.is_dataless(".a.pdf.icloud", fake_st(0)))
        self.assertEqual(fsguard.hold_reason(self.touch("a.pdf"), fake_st(fsguard.SF_DATALESS)), "iCloud에만 있음")

    def test_walk_treats_packages_as_one_item_and_skips_links_hidden_and_skip_dirs(self):
        self.touch("Report.pages/Index/Document.iwa")
        self.touch("Tool.app/Contents/MacOS/tool")
        self.touch("Odd.thing/Contents/Info.plist")
        self.touch("node_modules/x.js")
        self.touch(".hidden/a.txt")
        self.touch("docs/a.txt")
        os.symlink(self.root / "docs", self.root / "link")
        got = {(str(p.relative_to(self.root)), kind) for p, _, kind in
               fsguard.walk(self.root, skip_dirs={"node_modules"})}
        self.assertEqual(got, {("Report.pages", "package"), ("Tool.app", "package"),
                               ("Odd.thing", "package"), ("docs/a.txt", "file")})

    def test_walk_max_depth(self):
        self.touch("a/b/c/deep.txt")
        self.touch("a/top.txt")
        got = {p.name for p, _, _ in fsguard.walk(self.root, max_depth=1)}
        self.assertEqual(got, {"top.txt"})

    def test_protected_tree(self):
        self.touch("vault/.obsidian/app.json")
        self.touch("plain/a.md")
        self.assertTrue(fsguard.is_protected_tree(self.root / "vault"))
        self.assertFalse(fsguard.is_protected_tree(self.root / "plain"))

    def test_hold_reasons_for_lock_open_and_recent_files(self):
        self.assertEqual(fsguard.hold_reason(self.touch("~$ther.docx")), "잠금 파일")
        doc = self.touch("Report.docx")
        self.assertIsNone(fsguard.hold_reason(doc))
        self.touch("~$port.docx")
        self.assertEqual(fsguard.hold_reason(doc), "편집 중")
        lo = self.touch("sheet.ods")
        self.touch(".~lock.sheet.ods#")
        self.assertEqual(fsguard.hold_reason(lo), "편집 중")
        self.assertEqual(fsguard.hold_reason(self.touch("new.txt", age=10)), "방금 바뀜")
        self.assertIsNone(fsguard.hold_reason(self.touch("new2.txt", age=10), recent_window=0))

    def test_hold_reason_for_readonly_folder(self):
        p = self.touch("ro/a.txt")
        os.chmod(p.parent, 0o500)
        try:
            self.assertEqual(fsguard.hold_reason(p), "쓰기 권한 없음")
        finally:
            os.chmod(p.parent, 0o700)

    def test_name_key_unquotes_normalizes_and_folds_case(self):
        nfd = "보고서.pdf".encode().decode()  # 아래에서 NFD로 만든다
        import unicodedata
        self.assertEqual(fsguard.name_key(unicodedata.normalize("NFD", nfd)), fsguard.name_key("보고서.PDF"))
        self.assertEqual(fsguard.name_key("my%20file.txt"), "my file.txt")

    def test_reserve_is_exclusive_even_for_case_only_differences(self):
        self.touch("Report.pdf")
        with self.assertRaises(FileExistsError):
            fsguard.reserve(self.root / "report.pdf")
        with self.assertRaises(FileExistsError):
            fsguard.reserve(self.root / "Report.pdf")
        p = fsguard.reserve(self.root / "other.pdf")
        self.assertEqual(p.stat().st_size, 0)


if __name__ == "__main__":
    unittest.main()
