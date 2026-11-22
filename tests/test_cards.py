import io
import os
import sqlite3
import stat
import tempfile
import time
import unittest
from pathlib import Path
from contextlib import redirect_stderr
from unittest import mock

from ro import cards, cli, fsguard

_real_connect = cards.connect


def _fast_connect(*a, **k):
    """잠금 대기 5초를 0.1초로 줄인 connect(테스트 시간용)."""
    con = _real_connect(*a, **k)
    con.execute("PRAGMA busy_timeout=100")
    return con

WORDS = ("계약 조건 검토 결과 지급 일정 변경 사항 확인 필요 담당자 회신 기한 다음 주 금요일 까지 "
         "추가 자료 요청 및 견적 비교 표 첨부 예정 입니다 회의 일정 조율 바랍니다").split()


def body(n=60, seed=0):
    return " ".join(WORDS[(i * 7 + seed) % len(WORDS)] + str(i % 13) for i in range(n))


class CardsTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        t = Path(self.tmp.name).resolve()
        self.home = t / "ro"
        self.root = t / "Downloads"
        self.root.mkdir()
        self.t = time.time()
        self.home_patch = mock.patch("pathlib.Path.home", return_value=t)   # CLI 경로 검사는 홈 아래만 받는다
        self.home_patch.start()

    def tearDown(self):
        self.home_patch.stop()
        self.tmp.cleanup()

    def w(self, name, text):
        p = self.root / name
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(text)
        os.utime(p, (self.t - 3600, self.t - 3600))
        return p

    def scan(self, **kw):
        return cards.scan([str(self.root)], self.home, **kw)

    def rows(self):
        con = cards.connect(self.home, read_only=True)
        try:
            return {Path(r["path"]).name: dict(r) for r in con.execute("SELECT * FROM cards WHERE gone IS NULL")}
        finally:
            con.close()

    def relations(self):
        con = cards.connect(self.home, read_only=True)
        try:
            return [r["kind"] for r in con.execute("SELECT kind FROM relations")]
        finally:
            con.close()

    def test_db_is_private_and_rename_keeps_card_by_inode(self):
        self.w("a.txt", body())
        self.scan()
        self.assertEqual(stat.S_IMODE(cards.db_path(self.home).stat().st_mode), 0o600)
        cid = self.rows()["a.txt"]["card_id"]
        os.rename(self.root / "a.txt", self.root / "b.txt")
        res = self.scan()
        self.assertEqual(self.rows()["b.txt"]["card_id"], cid)   # 규칙 1
        self.assertEqual(res.get("gone", 0), 0)

    def test_atomic_save_with_similar_body_keeps_card_and_different_body_replaces(self):
        p = self.w("memo.txt", body(80))
        self.scan()
        cid = self.rows()["memo.txt"]["card_id"]
        tmp = self.root / ".tmp"
        tmp.write_text(body(80) + " 한 줄 더 덧붙임")
        os.replace(tmp, p)                                       # 새 inode, 내용은 거의 같다
        self.scan()
        self.assertEqual(self.rows()["memo.txt"]["card_id"], cid)  # 규칙 2(b)
        tmp.write_text(" ".join(f"전혀다른{i} 낱말{i} 묶음{i}" for i in range(40)))
        os.replace(tmp, p)
        self.scan()
        self.assertNotEqual(self.rows()["memo.txt"]["card_id"], cid)
        self.assertIn("replaced", self.relations())

    def test_move_across_folders_with_same_bytes_keeps_card(self):
        p = self.w("x.txt", body())
        self.scan()
        cid = self.rows()["x.txt"]["card_id"]
        sub = self.root / "sub"
        sub.mkdir()
        q = sub / "x.txt"
        q.write_bytes(p.read_bytes())       # 복사 후 삭제: inode가 바뀌는 이동
        p.unlink()
        res = self.scan()
        self.assertEqual(self.rows()["x.txt"]["card_id"], cid)   # 규칙 3
        self.assertEqual(res["moved"], 1)

    def test_deleted_file_is_marked_gone_only_after_full_scan(self):
        p = self.w("g.txt", "x")
        self.w("stay.txt", "y")
        self.scan()
        p.unlink()
        self.assertEqual(self.scan(wall_limit=-1)["stopped"], "시간")
        self.assertIn("g.txt", self.rows())                     # 다 못 훑었으면 사라짐을 판정하지 않는다
        self.scan()
        self.assertNotIn("g.txt", self.rows())

    def test_icloud_only_file_is_never_opened_and_gets_pending_relation(self):
        p = self.w("cloud.txt", body())
        self.scan()
        old = self.rows()["cloud.txt"]
        self.assertIsNotNone(old["sha"])
        tmp = self.root / ".tmp"
        tmp.write_text(body(seed=3))
        os.replace(tmp, p)
        opened = []
        real_open = open

        def spy(f, *a, **k):
            if str(f) == str(p):
                opened.append(f)
            return real_open(f, *a, **k)
        with mock.patch.object(fsguard, "is_dataless", lambda q, st=None: str(q) == str(p)), \
                mock.patch("builtins.open", spy):
            self.scan()
        r = self.rows()["cloud.txt"]
        self.assertEqual(opened, [])
        self.assertEqual((r["dataless"], r["sha"]), (1, None))
        self.assertIn("pending", self.relations())

    def test_packages_are_one_card_and_secrets_are_not_indexed(self):
        self.w("Deck.key/Data/a.png", "x")
        self.w("token.txt", "x")
        self.w("~$port.docx", "x")
        self.scan()
        rows = self.rows()
        self.assertEqual(set(rows), {"Deck.key"})
        self.assertEqual(rows["Deck.key"]["package"], 1)

    def test_minhash_similarity(self):
        a = cards.minhash({(str(i), "b", "c") for i in range(100)})
        b = cards.minhash({(str(i), "b", "c") for i in range(10, 110)})
        c = cards.minhash({(str(i), "x", "y") for i in range(100)})
        self.assertEqual(len(a), 128 * 8)
        self.assertGreater(cards.similarity(a, b), 0.6)
        self.assertLess(cards.similarity(a, c), 0.1)

    def test_report_counts_duplicates_versions_and_icloud(self):
        self.w("견적.txt", "same")
        self.w("견적 (1).txt", "same")
        self.w("보고서 v1.txt", "a")
        self.w("보고서 v2.txt", "b")
        with mock.patch.object(cards, "DEFAULT_ROOTS", [str(self.root)]):
            self.scan()
            rep = cards.report(self.home)
        self.assertEqual(rep["같은 내용 묶음"], 1)
        self.assertEqual(rep["판 여러 개인 문서 묶음"], 2)
        self.assertEqual(rep["폴더"]["Downloads"]["파일"], 4)

    def test_periodic_skips_on_battery_within_an_hour(self):
        class R:
            stdout = "Now drawing from 'Battery Power'"
        self.w("a.txt", "x")
        with mock.patch.object(cards, "DEFAULT_ROOTS", [str(self.root)]):
            first = cards.periodic(self.home, runner=lambda *a, **k: R())
            again = cards.periodic(self.home, now=time.time() + 60, runner=lambda *a, **k: R())
        self.assertNotIn("skipped", first)
        self.assertEqual(again, {"skipped": "배터리"})

    def test_pro_flag_does_not_unlock_mini(self):
        """RO-AUD-104: `--pro` 인자로는 pro가 켜지지 않는다. 번들 실행기 조건(키 없음)에서도 DB를 만들지 않는다."""
        self.w("a.txt", "x")
        for env in ({"RO_EDITION": "mini"}, {"RO_EDITION": "mini", "RO_EDITION_SOURCE": "license"}):
            with mock.patch.dict(os.environ, env):
                for argv in (["cards", "--pro", "--home", str(self.home), "scan", "--roots", str(self.root)],
                             ["cards", "--home", str(self.home), "--pro", "periodic"]):
                    err = io.StringIO()
                    with redirect_stderr(err):
                        self.assertEqual(cli.main(argv), 2)
                    self.assertNotIn("--pro", err.getvalue())   # 우회법을 안내하지 않는다
        self.assertFalse(cards.db_path(self.home).exists())

    def test_locked_db_fails_without_traceback_and_keeps_data(self):
        """RO-AUD-102: 다른 연결이 cards.db를 잡고 있으면 트레이스백 없이 안내하고, 이전 카드는 그대로다."""
        self.w("a.txt", body())
        self.scan()
        self.w("b.txt", body(seed=3))
        lock = sqlite3.connect(cards.db_path(self.home), timeout=0)
        lock.execute("BEGIN EXCLUSIVE")
        try:
            err = io.StringIO()
            with mock.patch.dict(os.environ, {"RO_EDITION": "pro"}), redirect_stderr(err), \
                    mock.patch.object(cards, "connect", side_effect=_fast_connect):
                rc = cli.main(["cards", "--home", str(self.home), "scan", "--roots", str(self.root)])
        finally:
            lock.rollback()
            lock.close()
        self.assertEqual(rc, 1)
        self.assertIn("잠겨", err.getvalue())
        con = sqlite3.connect(cards.db_path(self.home))
        self.assertEqual(con.execute("PRAGMA integrity_check").fetchone()[0], "ok")
        self.assertEqual(con.execute("SELECT COUNT(*) FROM cards").fetchone()[0], 1)   # 잠긴 동안의 훑기는 반영 안 됨
        con.close()
        self.assertEqual(self.scan()["new"], 1)   # 풀리면 다음 훑기가 이어서 한다

    def test_cli_paths_must_be_existing_folders_under_home(self):
        """RO-AUD-106: 없는 폴더·홈 밖 --roots, 홈 밖 --home은 rc 1과 안내로 거부하고 아무것도 만들지 않는다."""
        outside = Path(tempfile.mkdtemp())
        self.addCleanup(lambda: __import__("shutil").rmtree(outside, ignore_errors=True))
        cases = (["--home", str(self.home), "scan", "--roots", str(self.root / "없는폴더")],
                 ["--home", str(self.home), "scan", "--roots", str(outside)],
                 ["--home", str(self.home), "scan", "--roots", "/"],
                 ["--home", str(outside / "ro"), "scan", "--roots", str(self.root)],
                 ["--home", "", "report"])
        with mock.patch.dict(os.environ, {"RO_EDITION": "pro"}):
            for argv in cases:
                err = io.StringIO()
                with redirect_stderr(err):
                    self.assertEqual(cli.main(["cards", *argv]), 1, argv)
                self.assertTrue(err.getvalue().strip(), argv)
        self.assertFalse(cards.db_path(self.home).exists())
        self.assertEqual(list(outside.iterdir()), [])

    def test_cli_requires_pro_and_agent_only_previews(self):
        with mock.patch.dict(os.environ, {"RO_EDITION": "mini"}):
            self.assertEqual(cli.main(["cards", "--home", str(self.home), "report"]), 2)
        self.assertFalse(cards.db_path(self.home).exists())    # mini는 DB를 만들지 않는다
        plist = cards.agent_plist(home=self.home)
        self.assertEqual(plist["StartInterval"], 900)
        self.assertNotIn("--pro", plist["ProgramArguments"])   # 에디션은 EnvironmentVariables가 정한다
        self.assertEqual(plist["EnvironmentVariables"]["RO_EDITION"], "pro")
        launch = Path.home() / "Library/LaunchAgents" / f"{cards.LABEL}.plist"
        before = launch.exists()
        with mock.patch.dict(os.environ, {"RO_EDITION": "pro"}):
            cli.main(["cards", "--home", str(self.home), "agent"])
        self.assertEqual(launch.exists(), before)                 # 미리 보기만 한다


if __name__ == "__main__":
    unittest.main()
