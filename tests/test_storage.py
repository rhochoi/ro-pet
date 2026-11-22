"""ro storage 감사: 읽기 전용, 링크·민감 폴더 미진입, SQLite 헤더 판독, 앱 사용 기록 파싱."""
import json
import os
import sqlite3
import subprocess
import sys
import tempfile
import unittest
from datetime import datetime, timezone
from pathlib import Path

from ro import storage

REPO = Path(__file__).resolve().parent.parent


def _write(path, size):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(os.urandom(size))


def _snapshot(root):
    out = {}
    for dp, dns, fns in os.walk(root):
        for n in dns + fns:
            p = os.path.join(dp, n)
            st = os.lstat(p)
            out[p] = (st.st_mode, st.st_size, st.st_mtime_ns)
    return out


class StorageAuditTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.home = Path(self.tmp.name) / "home"
        self.outside = Path(self.tmp.name) / "outside"
        lib = self.home / "Library"
        _write(lib / "Caches/com.example.app/blob", 300_000)
        _write(lib / "Caches/com.example.app/sub/blob2", 100_000)
        _write(lib / "Caches/Notion.ShipIt/update.zip", 50_000)
        _write(lib / "Caches/com.apple.Safari/x", 50_000)  # OS 캐시는 보지 않는다
        _write(self.outside / "huge", 2_000_000)
        os.symlink(self.outside, lib / "Caches/com.example.app/link")  # 따라가지 않는다
        sup = lib / "Application Support"
        _write(sup / "Notion/Partitions/notion/Service Worker/CacheStorage/a", 80_000)
        _write(sup / "Notion/Code Cache/js/b", 40_000)
        _write(sup / "Google/Chrome/Default/Cache/c", 90_000)  # 브라우저 프로필은 들어가지 않는다
        _write(sup / "MobileSync/Backup/d", 90_000)
        (sup / "Evil").mkdir()
        os.symlink(self.outside, sup / "Evil/Cache")  # 앱 폴더 밖으로 나가는 링크
        _write(self.home / ".npm/_cacache/e", 20_000)
        self.db = sup / "SomeApp/data/store.db"
        self.db.parent.mkdir(parents=True)
        con = sqlite3.connect(self.db)
        con.execute("create table t(x)")
        con.executemany("insert into t values (?)", [(b"x" * 4000,)] * 200)
        con.commit()
        con.execute("delete from t")
        con.commit()
        con.close()

    def tearDown(self):
        self.tmp.cleanup()

    def audit(self):
        return storage.audit(self.home, apps=False, min_bytes=0)

    def test_read_only(self):
        before = _snapshot(self.tmp.name)
        storage.render(self.audit())
        self.assertEqual(before, _snapshot(self.tmp.name))

    def test_caches_skip_links_os_and_sensitive_dirs(self):
        r = self.audit()
        by = {c["display"]: c for c in r["caches"]}
        app = by["~/Library/Caches/com.example.app"]
        self.assertGreaterEqual(app["bytes"], 400_000)
        self.assertLess(app["bytes"], 2_000_000)  # 링크 너머 2MB는 세지 않음
        self.assertEqual(app["files"], 2)
        self.assertEqual(by["~/Library/Caches/Notion.ShipIt"]["kind"], "update-leftover")
        self.assertIn("~/Library/Application Support/Notion/Partitions/notion/Service Worker/CacheStorage", by)
        self.assertIn("~/Library/Application Support/Notion/Code Cache", by)
        self.assertEqual(by["~/.npm/_cacache"]["kind"], "dev-cache")
        joined = " ".join(by)
        for banned in ("com.apple.Safari", "Google", "MobileSync", "Evil"):
            self.assertNotIn(banned, joined)

    def test_sqlite_freelist_from_header(self):
        rows = storage.sqlite_free(self.home, min_free=1)
        self.assertEqual([r["display"] for r in rows], ["~/Library/Application Support/SomeApp/data/store.db"])
        con = sqlite3.connect(self.db)
        page, free = con.execute("pragma page_size").fetchone()[0], con.execute("pragma freelist_count").fetchone()[0]
        con.close()
        self.assertGreater(free, 0)
        self.assertEqual(rows[0]["bytes"], page * free)

    def test_not_sqlite_is_ignored(self):
        (self.home / "Library/Application Support/SomeApp/fake.db").write_bytes(b"x" * 200)
        self.assertEqual(len(storage.sqlite_free(self.home, min_free=1)), 1)

    def test_budget_marks_partial(self):
        r = storage.audit(self.home, apps=False, min_bytes=0, budget=-1)
        self.assertTrue(r["partial"])
        self.assertIn("일부만", storage.render(r))

    def test_applications_parse_mdls(self):
        apps = Path(self.tmp.name) / "Applications"
        for n in ("A.app", "B.app", "C.app"):
            (apps / n).mkdir(parents=True)
        out = b"2026-11-10 10:00:00 +0000\x001000\x00(null)\x00(null)\x002026-01-01 00:00:00 +0000\x00500"

        def runner(cmd, **kw):
            self.assertEqual(cmd[:2], ["mdls", "-raw"])
            return subprocess.CompletedProcess(cmd, 0, out, b"")

        now = datetime(2026, 11, 12, tzinfo=timezone.utc)
        rows = {a["display"]: a for a in storage.applications(apps, now=now, runner=runner)}
        self.assertEqual((rows["A.app"]["days_since_use"], rows["A.app"]["stale"], rows["A.app"]["bytes"]), (1, False, 1000))
        self.assertEqual((rows["B.app"]["last_used"], rows["B.app"]["stale"], rows["B.app"]["bytes"]), ("never_recorded", True, None))
        self.assertTrue(rows["C.app"]["stale"])

    def test_applications_mdls_failure_is_unknown(self):
        apps = Path(self.tmp.name) / "Applications"
        (apps / "A.app").mkdir(parents=True)
        fail = lambda cmd, **kw: subprocess.CompletedProcess(cmd, 1, b"", b"err")  # noqa: E731
        row = storage.applications(apps, runner=fail)[0]
        self.assertEqual((row["last_used"], row["stale"]), ("unknown", False))

    def test_cli_json(self):
        env = {**os.environ, "HOME": str(self.home)}
        r = subprocess.run([sys.executable, "-m", "ro", "storage", "--json", "--no-apps"], cwd=REPO, env=env,
                           capture_output=True, text=True, timeout=60)
        self.assertEqual(r.returncode, 0, r.stderr)
        report = json.loads(r.stdout)
        self.assertGreater(report["cache_total"], 0)
        self.assertEqual(report["apps"], [])


if __name__ == "__main__":
    unittest.main()
