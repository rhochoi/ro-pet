import os
import tempfile
import time
import unittest
from pathlib import Path
from unittest import mock

from ro import fsguard, journal


class JournalTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        t = Path(self.tmp.name).resolve()
        self.h = t / "home"
        self.dl = self.h / "Downloads"
        self.docs = self.h / "Documents"
        self.dl.mkdir(parents=True)
        self.docs.mkdir()
        self.ro = self.h / ".ro"
        self.p = mock.patch("pathlib.Path.home", return_value=self.h)
        self.p.start()

    def tearDown(self):
        self.p.stop()
        self.tmp.cleanup()

    def w(self, path, text="x", age=3600):
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text)
        os.utime(path, (time.time() - age,) * 2)
        return path

    def batch(self):
        return journal.Batch("test", [self.dl, self.docs], self.ro)

    def snapshot(self):
        return sorted(str(p.relative_to(self.h)) for p in self.h.rglob("*") if ".ro" not in p.parts)

    def test_multi_root_tree_change_undoes_in_reverse(self):
        self.w(self.dl / "a.pdf")
        self.w(self.dl / "proj" / "b.txt")
        self.w(self.dl / "proj" / ".hidden")
        (self.dl / "Deck.key" / "Data").mkdir(parents=True)
        before = self.snapshot()
        with self.batch() as b:
            b.mkdir(self.docs / "업무")
            b.move(self.dl / "a.pdf", self.docs / "업무" / "a.pdf")
            b.move(self.dl / "Deck.key", self.docs / "업무" / "Deck.key")   # 패키지는 통째로
            b.move_dir_contents(self.dl / "proj", self.docs / "업무" / "proj")
            b.rmdir_if_empty(self.dl / "proj")
        self.assertFalse((self.dl / "proj").exists())
        self.assertTrue((self.docs / "업무" / "proj" / ".hidden").exists())
        t0 = time.monotonic()
        _, restored, skipped = journal.undo(home=self.ro)
        self.assertLess(time.monotonic() - t0, 1.0)
        self.assertEqual(skipped, [])
        self.assertEqual(restored, 7)
        self.assertEqual(self.snapshot(), before)

    def test_failure_inside_batch_rolls_back_immediately(self):
        self.w(self.dl / "a.txt")
        before = self.snapshot()
        with self.assertRaises(journal.JournalError):
            with self.batch() as b:
                b.mkdir(self.docs / "새폴더")
                b.move(self.dl / "a.txt", self.docs / "새폴더" / "a.txt")
                b.move(self.h / "x", self.docs / "y")             # 허용 루트 밖 → 배치 전체를 바로 되돌린다
        self.assertEqual(self.snapshot(), before)

    def test_crash_after_intent_is_recovered_from_file_state(self):
        self.w(self.dl / "a.txt")
        self.w(self.dl / "b.txt")
        before = self.snapshot()
        b = self.batch().__enter__()
        b.mkdir(self.docs / "묶음")
        b.move(self.dl / "a.txt", self.docs / "묶음" / "a.txt")
        real_write = journal._write

        def die_after_move(home, entry):    # 두 번째 이동은 실제로 되었지만 'done'을 쓰기 전에 죽는다
            if entry.get("state") == "done" and entry.get("src", "").endswith("b.txt"):
                raise KeyboardInterrupt
            real_write(home, entry)
        with mock.patch.object(journal, "_write", die_after_move):
            with self.assertRaises(KeyboardInterrupt):
                b.move(self.dl / "b.txt", self.docs / "묶음" / "b.txt")
        res = journal.recover(self.ro)        # 다음 기동 때
        self.assertEqual(len(res), 1)
        self.assertEqual(res[0][1], 3)
        self.assertEqual(self.snapshot(), before)
        self.assertEqual(journal.recover(self.ro), [])

    def test_bad_lines_do_not_block_recover(self):
        """RO-AUD-103: 객체가 아닌 JSON·op 없는 줄이 섞여도 미커밋 배치를 되돌린다."""
        self.w(self.dl / "a.txt")
        before = self.snapshot()
        b = self.batch().__enter__()
        b.move(self.dl / "a.txt", self.docs / "a.txt")   # commit 전에 멈춘 셈
        with open(journal._path(self.ro), "a") as f:
            f.write('[1,2]\n{}\n"x"\n{"op": 3}\n{broken\n')
        res = journal.recover(self.ro)
        self.assertEqual([r[1] for r in res], [1])
        self.assertEqual(self.snapshot(), before)
        self.assertEqual(journal.recover(self.ro), [])

    def test_crash_after_reserve_drops_placeholder(self):
        self.w(self.dl / "a.txt")
        b = self.batch().__enter__()
        with mock.patch.object(journal.os, "replace", side_effect=KeyboardInterrupt):
            with self.assertRaises(KeyboardInterrupt):
                b.move(self.dl / "a.txt", self.docs / "a.txt")
        self.assertTrue((self.docs / "a.txt").exists())   # 빈 자리 표시만 남았다
        journal.recover(self.ro)
        self.assertFalse((self.docs / "a.txt").exists())
        self.assertTrue((self.dl / "a.txt").exists())

    def test_undo_leaves_things_that_changed_since(self):
        self.w(self.dl / "a.txt")
        with self.batch() as b:
            b.move(self.dl / "a.txt", self.docs / "a.txt")
        self.w(self.docs / "a.txt.new", "다른 파일")      # 같은 이름, 다른 inode(옛 파일이 있는 동안 만들어야
        os.replace(self.docs / "a.txt.new", self.docs / "a.txt")  # Linux가 지운 inode 번호를 다시 쓰지 않는다)
        _, restored, skipped = journal.undo(home=self.ro)
        self.assertEqual(restored, 0)
        self.assertIn("바뀜", skipped[0][1])
        self.assertTrue((self.docs / "a.txt").exists())

    def test_refuses_outside_roots_protected_trees_icloud_and_existing_names(self):
        self.w(self.dl / "a.txt")
        self.w(self.h / "Music" / "m.mp3")
        self.w(self.docs / "vault" / ".obsidian" / "app.json")
        self.w(self.docs / "A.TXT")
        with self.batch() as b:
            for src, dst in ((self.h / "Music" / "m.mp3", self.docs / "m.mp3"),
                             (self.dl / "a.txt", self.docs / "vault" / "a.txt"),
                             (self.dl / "a.txt", self.docs / "a.txt")):
                with self.assertRaises((journal.JournalError, FileExistsError)):
                    b.move(src, dst)
            with mock.patch.object(fsguard, "is_dataless", lambda q, st=None: True):
                with self.assertRaises(journal.JournalError):
                    b.move(self.dl / "a.txt", self.docs / "b.txt")
        self.assertTrue((self.dl / "a.txt").exists())
        with self.assertRaises(journal.JournalError):
            journal.Batch("x", [self.h], self.ro)            # 홈 전체는 허용 루트가 될 수 없다

    def test_protection_markers_above_the_root_do_not_block(self):
        (self.h / ".vscode").mkdir()                     # 홈의 ~/.vscode는 흔하다
        self.w(self.dl / "a.txt")
        with self.batch() as b:
            b.move(self.dl / "a.txt", self.docs / "a.txt")
        self.assertTrue((self.docs / "a.txt").exists())

    def test_cross_volume_is_refused_without_copy(self):
        self.w(self.dl / "a.txt")
        err = OSError(journal.errno.EXDEV, "x")
        with self.batch() as b:
            with mock.patch.object(journal.os, "replace", side_effect=err):
                with self.assertRaises(journal.JournalError):
                    b.move(self.dl / "a.txt", self.docs / "a.txt")
        self.assertTrue((self.dl / "a.txt").exists())
        self.assertFalse((self.docs / "a.txt").exists())


if __name__ == "__main__":
    unittest.main()
