import os
import sqlite3
import stat
import tempfile
import time
import unittest
from pathlib import Path
from unittest import mock

from ro import config, journal, pet, profile

DAY = 86400


class ProfileTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name).resolve()
        self.home = self.root / ".ro"
        self.docs = self.root / "Documents" / "세금"
        self.docs.mkdir(parents=True)
        self.t0 = time.mktime(time.strptime("2026-11-02 10:00", "%Y-%m-%d %H:%M"))

    def tearDown(self):
        self.tmp.cleanup()

    def obs(self, at, kind="ext_home", key=".pdf", value=None):
        return profile.observe(kind, key, str(value or self.docs), home=self.home, now=at)

    def items(self, now):
        return profile.learned(self.home, now=now, roots=[self.root / "Documents"])

    def test_nothing_is_learned_or_created_before_consent(self):
        with self.assertRaises(profile.NotAllowed):
            self.obs(self.t0)
        self.assertFalse(profile.db_path(self.home).exists())
        self.assertEqual(profile.prior("ext_home", ".pdf", home=self.home), [])

    def test_episodes_daily_cap_and_three_day_promotion(self):
        profile.set_consent(self.home)
        self.assertTrue(self.obs(self.t0))
        self.assertFalse(self.obs(self.t0 + 600))              # 같은 에피소드
        self.assertFalse(self.obs(self.t0 + 3 * 3600))         # 새 에피소드지만 같은 날
        self.assertEqual(self.items(self.t0)[0]["status"], "watching")
        self.assertTrue(self.obs(self.t0 + DAY))
        self.assertEqual(self.items(self.t0 + DAY)[0]["status"], "watching")
        self.assertTrue(self.obs(self.t0 + 2 * DAY))
        item = self.items(self.t0 + 2 * DAY)[0]
        self.assertEqual((item["status"], item["days"]), ("learned", 3))
        self.assertTrue(item["value"].endswith("Documents/세금"))
        tok = profile.folder_token(self.docs, home=self.home)
        self.assertEqual(profile.prior("ext_home", ".pdf", home=self.home, now=self.t0 + 2 * DAY), [tok])

    def test_db_holds_no_names_or_paths_and_is_private(self):
        profile.set_consent(self.home)
        self.obs(self.t0)
        self.obs(self.t0, kind="app_band", key="오전", value="Keynote")
        raw = profile.db_path(self.home).read_bytes()
        self.assertNotIn("세금".encode(), raw)
        self.assertNotIn(str(self.root).encode(), raw)
        self.assertEqual(stat.S_IMODE(os.stat(profile.db_path(self.home)).st_mode), 0o600)
        for bad in ("a/b.pdf", "x" * 60, "보고서\n"):
            with self.assertRaises(ValueError):
                profile.observe("ext_home", bad, str(self.docs), home=self.home)
        with self.assertRaises(ValueError):
            profile.observe("app_band", "오전", "/Users/x/secret", home=self.home)
        with self.assertRaises(ValueError):
            profile.observe("filename", ".pdf", "x", home=self.home)

    def test_decay_forgets_unless_pinned(self):
        profile.set_consent(self.home)
        for d in range(3):
            self.obs(self.t0 + d * DAY)
            self.obs(self.t0 + d * DAY, key=".hwp")
        pid = next(i["id"] for i in self.items(self.t0 + 3 * DAY) if i["key"] == ".hwp")
        self.assertTrue(profile.pin(pid, home=self.home))
        later = self.t0 + 90 * DAY
        left = self.items(later)
        self.assertEqual([(i["key"], i["status"]) for i in left], [(".hwp", "pinned")])
        self.assertEqual(len(profile.prior("ext_home", ".hwp", home=self.home, now=later)), 1)

    def test_off_items_are_never_relearned_and_forget_deletes(self):
        profile.set_consent(self.home)
        for d in range(3):
            self.obs(self.t0 + d * DAY)
        pid = self.items(self.t0 + 2 * DAY)[0]["id"]
        self.assertTrue(profile.turn_off(pid, home=self.home))
        self.assertFalse(self.obs(self.t0 + 3 * DAY))
        self.assertEqual(profile.prior("ext_home", ".pdf", home=self.home, now=self.t0 + 3 * DAY), [])
        self.assertEqual(self.items(self.t0 + 3 * DAY)[0]["status"], "off")
        self.assertTrue(profile.forget(pid, home=self.home))
        self.assertEqual(self.items(self.t0 + 3 * DAY), [])

    def test_missing_folder_is_shown_without_a_name(self):
        profile.set_consent(self.home)
        gone = self.root / "Documents" / "옛폴더"
        self.obs(self.t0, value=gone)
        self.assertEqual(self.items(self.t0)[0]["value"], "사라진 폴더")

    def test_wipe_removes_db_salt_and_consent(self):
        profile.set_consent(self.home)
        self.obs(self.t0)
        tok = profile.folder_token(self.docs, home=self.home)
        self.assertTrue(profile.wipe(self.home))
        self.assertFalse(profile.consented(self.home))
        self.assertFalse(profile.db_path(self.home).exists())
        profile.set_consent(self.home)
        self.obs(self.t0)
        self.assertNotEqual(profile.folder_token(self.docs, home=self.home), tok)   # 새 소금

    def test_concurrent_writer_waits(self):
        profile.set_consent(self.home)
        self.obs(self.t0)
        other = sqlite3.connect(profile.db_path(self.home))
        other.execute("BEGIN IMMEDIATE")
        try:
            con = profile._connect(self.home)
            self.assertEqual(con.execute("PRAGMA busy_timeout").fetchone()[0], 5000)
            con.close()
        finally:
            other.rollback()
            other.close()


class ProfileWiringTest(unittest.TestCase):
    """mini에서는 DB도 안 생기고, ro pro에서 동의했을 때만 곁들여 배운다."""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.h = Path(self.tmp.name).resolve() / "home"
        self.ro = self.h / ".ro"
        (self.h / "Downloads").mkdir(parents=True)
        (self.h / "Documents" / "세금").mkdir(parents=True)
        self.p = mock.patch("pathlib.Path.home", return_value=self.h)
        self.p.start()

    def tearDown(self):
        self.p.stop()
        self.tmp.cleanup()

    def move_one(self, learn=True, name="고지서.pdf"):
        f = self.h / "Downloads" / name
        f.write_text("x")
        with journal.Batch("test", [self.h / "Downloads", self.h / "Documents"], self.ro, learn=learn) as b:
            b.move(f, self.h / "Documents" / "세금" / f.name)

    def test_mini_never_creates_memory_db_even_if_consent_was_left_on(self):
        profile.set_consent(self.ro)
        with mock.patch.dict("os.environ", {"RO_EDITION": "mini"}):
            self.assertFalse(profile.observe_quiet("ext_home", ".pdf", self.h, home=self.ro))
            self.move_one()
            rt = pet.PetRuntime(home=self.ro, log_dir=str(self.ro / "logs"), edition="mini")
            self.assertFalse(rt.on_host_line('{"type": "front", "app": "Keynote"}'))
            self.assertFalse(rt.learned_api({"op": "list"})["ok"])
        self.assertFalse(profile.db_path(self.ro).exists())

    def test_pro_learns_from_approved_moves_and_front_app_only_with_consent(self):
        with mock.patch.dict("os.environ", {"RO_EDITION": "pro"}):
            self.move_one()
            self.assertFalse(profile.db_path(self.ro).exists())          # 동의 전
            rt = pet.PetRuntime(home=self.ro, log_dir=str(self.ro / "logs"), edition="pro")
            res = rt.learned_api({"op": "consent", "on": True})
            self.assertTrue(res["ok"] and res["learning"])
            self.move_one(name="영수증.pdf")
            rt.on_host_line('{"type": "front", "app": "Keynote", "t": 1800000000}')
            rt.on_host_line('{"type": "front", "app": "1Password 8", "t": 1800000000}')
            items = profile.learned(self.ro, roots=[self.h / "Documents"])
            whats = sorted(i["what"] for i in items)
            self.assertEqual(len(items), 2, whats)
            self.assertTrue(any(i["value"] == "~/Documents/세금" for i in items))
            self.assertTrue(any(i["value"] == "Keynote" for i in items))
            pid = items[0]["id"]
            self.assertTrue(rt.learned_api({"op": "off", "id": pid})["ok"])
            self.assertFalse(rt.learned_api({"op": "off", "id": "1"})["ok"])
            self.assertFalse(rt.learned_api({"op": "wipe"})["ok"])                # 확인 없이 지우지 않는다
            self.assertTrue(rt.learned_api({"op": "wipe", "approve": True})["ok"])
            self.assertFalse(profile.db_path(self.ro).exists())

    def test_nudge_consent_and_turned_off_types_are_editable(self):
        rt = pet.PetRuntime(home=self.ro, log_dir=str(self.ro / "logs"), edition="pro")
        self.assertTrue(rt.learned_api({"op": "nudges", "on": True})["nudges"])
        config.update(self.ro, nudges_off=["dmg_installed", "disk_low"])
        res = rt.learned_api({"op": "type_on", "trigger": "dmg_installed"})
        self.assertEqual(res["nudges_off"], ["disk_low"])
        self.assertFalse(rt.learned_api({"op": "nudges", "on": "yes"})["ok"])


if __name__ == "__main__":
    unittest.main()
