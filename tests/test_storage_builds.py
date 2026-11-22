import os
import tempfile
import time
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest import mock

from ro import journal, storage

OLD = time.time() - 200 * 86400


def clean_git(*a, **k):
    return SimpleNamespace(returncode=0, stdout="")


class DeadBuildsTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.h = Path(self.tmp.name).resolve() / "home"
        self.dev = self.h / "Developer"
        self.ro = self.h / ".ro"
        self.p = mock.patch("pathlib.Path.home", return_value=self.h)
        self.p.start()

    def tearDown(self):
        self.p.stop()
        self.tmp.cleanup()

    def project(self, name, marker, build, age=OLD, size=2048):
        proj = self.dev / name
        (proj / build / "lib").mkdir(parents=True)
        (proj / build / "lib" / "big.bin").write_bytes(b"0" * size)
        (proj / marker).write_text("{}")
        (proj / "main.py").write_text("x")
        (proj / ".git").mkdir()
        for f in (proj / marker, proj / "main.py"):
            os.utime(f, (age, age))
        return proj

    def find(self, runner=clean_git):
        return storage.dead_builds([str(self.dev)], runner=runner, min_bytes=1)

    def test_finds_only_idle_rebuildable_clean_projects(self):
        self.project("old-node", "package.json", "node_modules")
        self.project("old-py", "pyproject.toml", ".venv")
        self.project("fresh", "package.json", "node_modules", age=time.time())
        self.project("no-marker", "README.md", "node_modules")
        found = {Path(x["path"]).parent.name: x for x in self.find()}
        self.assertEqual(set(found), {"old-node", "old-py"})
        self.assertGreaterEqual(found["old-node"]["idle_days"], 199)
        dirty = lambda *a, **k: SimpleNamespace(returncode=0, stdout=" M main.py\n")
        self.assertEqual(self.find(runner=dirty), [])          # 커밋 안 한 변경이 있으면 건드리지 않는다

    def test_quarantine_moves_whole_folder_and_undo_restores_it(self):
        proj = self.project("old-node", "package.json", "node_modules")
        (proj / ".vscode").mkdir()                             # 편집기 설정이 있어도 빌드 폴더 격리는 된다
        target = proj / "node_modules"
        batch, moved, skipped = storage.quarantine_builds([target], self.ro)
        self.assertEqual((len(moved), skipped), (1, []))
        self.assertFalse(target.exists())
        boxed = list((self.ro / "cleanup" / "trash" / batch).iterdir())
        self.assertTrue((boxed[0] / "lib" / "big.bin").exists())
        journal.undo(batch, self.ro)
        self.assertTrue((target / "lib" / "big.bin").exists())

    def test_quarantine_refuses_non_build_folders(self):
        proj = self.project("old-node", "package.json", "node_modules")
        with self.assertRaises(ValueError):
            storage.quarantine_builds([proj], self.ro)


if __name__ == "__main__":
    unittest.main()
