import json
import os
import tempfile
import time
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest import mock

from ro import config, designmetrics, fsguard, pet, prowatch, scenarios, staging

T0 = 1_800_000_000.0


def touch(p, age=0.0, size=1, now=None):
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_bytes(b"x" * size)
    t = (now or time.time()) - age
    os.utime(p, (t, t))
    return p


class ScenarioTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.h = Path(self.tmp.name).resolve() / "home"
        self.dl = self.h / "Downloads"
        self.apps = self.h / "Applications"
        self.dl.mkdir(parents=True)
        self.apps.mkdir()
        self.log = str(self.h / ".ro" / "logs")

    def tearDown(self):
        self.tmp.cleanup()

    def test_installer_counts_only_when_matching_app_appeared_after_it(self):
        dmg = touch(self.dl / "Firefox 131.0.2.dmg", age=3600)
        touch(self.dl / "Zoom-arm64.pkg", age=3600)
        touch(self.dl / "fresh-Firefox.dmg", age=60)                 # 막 내려받음
        (self.apps / "Firefox.app").mkdir()
        old = self.apps / "Zoom.app"
        old.mkdir()
        os.utime(old, (time.time() - 86400,) * 2)                    # 설치 파일보다 먼저 있던 앱
        hits = scenarios.installed_installers(self.dl, [self.apps])
        self.assertEqual([h["path"] for h in hits], [str(dmg)])
        self.assertEqual(hits[0]["app"], "Firefox.app")

    def test_newer_version_by_name_only(self):
        a = touch(self.h / "Docs" / "제안서_v2.key", age=86400 * 3)
        b = touch(self.h / "Docs" / "제안서_v3.key", age=86400)
        self.assertEqual(scenarios.newer_version(a), str(b))
        self.assertIsNone(scenarios.newer_version(b))
        with mock.patch("builtins.open", side_effect=AssertionError("열지 않는다")):
            scenarios.newer_version(a)

    def test_evict_candidates_skip_small_recent_and_dataless(self):
        root = self.h / "iCloud"
        big_old = touch(root / "영상.mov", age=90 * 86400, size=2048)
        touch(root / "새영상.mov", age=86400, size=2048)
        touch(root / "작은.pdf", age=90 * 86400, size=10)
        cloud = touch(root / "구름.mov", age=90 * 86400, size=2048)
        real = fsguard.is_dataless
        with mock.patch.object(fsguard, "is_dataless", lambda p, st=None: Path(p) == cloud or real(p, st)):
            out = scenarios.evict_candidates(root, min_bytes=1024)
        self.assertEqual([o["path"] for o in out], [str(big_old)])

    def test_seek_watch_needs_many_switches_between_folders(self):
        w = scenarios.SeekWatch()
        seq = ["/a", "/b", "/a", "/b"]
        self.assertTrue(all(w.on_folder(f, T0 + i) is None for i, f in enumerate(seq)))
        self.assertEqual(w.on_folder("/c", T0 + 5)["switches"], 4)
        w2 = scenarios.SeekWatch()
        for i, f in enumerate(["/a", "/b", "/a", "/b", "/a"]):
            hit = w2.on_folder(f, T0 + i * 60)                        # 2분 창 밖으로 흩어지면 없음
        self.assertIsNone(hit)

    def test_trust_stage_from_accepts_minus_undos(self):
        self.assertEqual(scenarios.trust(self.log, T0), (1, 0))
        for _ in range(6):
            designmetrics.record_nudge("dmg_installed", "accepted", log_dir=self.log, at=T0 - 60)
        self.assertEqual(scenarios.trust(self.log, T0)[0], 2)
        designmetrics.record_nudge("dmg_installed", "undone", log_dir=self.log, at=T0 - 30)
        designmetrics.record_nudge("dmg_installed", "undone", log_dir=self.log, at=T0 - 30)
        self.assertEqual(scenarios.trust(self.log, T0), (1, 4))
        self.assertNotIn("move", scenarios.allowed_ops(1))
        self.assertIn("move", scenarios.allowed_ops(2))


class StagingTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.h = Path(self.tmp.name).resolve() / "home"
        self.dl = self.h / "Downloads"
        self.dl.mkdir(parents=True)
        self.ro = self.h / ".ro"
        self.log = str(self.ro / "logs")
        self.p = mock.patch("pathlib.Path.home", return_value=self.h)
        self.p.start()
        self.calls = []
        self.st = staging.Stage(self.ro, self.log, runner=self.fake_run)

    def tearDown(self):
        self.p.stop()
        self.tmp.cleanup()

    def fake_run(self, args, **kw):
        self.calls.append(args)
        return SimpleNamespace(returncode=0, stdout="", stderr="")

    def test_sure_items_preselected_meta_items_capped_and_approval_required(self):
        a = touch(self.dl / "a.dmg", age=3600)
        b = touch(self.dl / "b.mov", age=3600)
        cid = self.st.open("disk", "disk_low", [staging.item("quarantine", a, 0.95, "설치됨"),
                                                 staging.item("evict", b, 0.99, "오래 안 씀")], [self.dl], "후보")
        view = self.st.view(cid)
        self.assertEqual([(i["sure"], i["confidence"]) for i in view["items"]], [(True, 0.95), (False, 0.75)])
        self.assertNotIn(str(self.dl), json.dumps(view, ensure_ascii=False))   # 화면에는 이름만
        with self.assertRaises(staging.StageError):
            self.st.apply(cid, [1])
        with self.assertRaises(staging.StageError):
            self.st.apply(cid, [9], approve=True)
        self.assertTrue(a.exists())

    def test_apply_moves_only_picked_into_trash_and_undo_restores(self):
        a = touch(self.dl / "a.dmg", age=3600)
        b = touch(self.dl / "b.pkg", age=3600)
        cid = self.st.open("installer", "dmg_installed", [staging.item("quarantine", a, 0.95, "x"),
                                                          staging.item("quarantine", b, 0.95, "x")], [self.dl], "t")
        res = self.st.apply(cid, [1], approve=True)
        self.assertEqual(res["moved"], [1])
        self.assertFalse(a.exists())
        self.assertTrue(b.exists())
        self.assertEqual(len(list((self.ro / "cleanup" / "trash").rglob("*a.dmg"))), 1)
        with self.assertRaises(staging.StageError):
            self.st.apply(cid, [2], approve=True)                      # 한 카드는 한 번
        res = self.st.undo(cid)
        self.assertEqual((res["restored"], res["files"]), (2, 1))          # mkdir + move, 파일은 1개
        self.assertTrue(a.exists())
        self.assertEqual(scenarios.trust(self.log)[1], -1)              # 되돌림은 신뢰를 깎는다

    def test_evict_runs_brctl_only_for_local_unlocked_files(self):
        a = touch(self.dl / "a.mov", age=3600)
        b = touch(self.dl / "b.mov", age=3600)
        touch(self.dl / "~$b.mov")                                      # 잠금 파일 → 편집 중
        cid = self.st.open("disk", "disk_low", [staging.item("evict", a, 0.75, "x"),
                                                 staging.item("evict", b, 0.75, "x")], [self.dl], "t")
        res = self.st.apply(cid, [1, 2], approve=True)
        self.assertEqual(res["evicted"], [1])
        self.assertEqual(self.calls, [["brctl", "evict", str(a)]])
        self.assertEqual(res["skipped"][0][0], 2)

    def test_structural_cards_need_trust(self):
        a = touch(self.dl / "a.pdf", age=3600)
        with self.assertRaises(staging.StageError):
            self.st.open("assist", "assist", [staging.item("move", a, 0.95, "x", dest=self.h / "Documents")],
                         [self.dl, self.h / "Documents"], "t")


class ProWatchTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.h = Path(self.tmp.name).resolve() / "home"
        self.dl = self.h / "Downloads"
        self.dl.mkdir(parents=True)
        self.ro = self.h / ".ro"
        self.p = mock.patch("pathlib.Path.home", return_value=self.h)
        self.p.start()
        self.rt = pet.PetRuntime(home=str(self.ro), log_dir=str(self.ro / "logs"), edition="pro")
        config.update(str(self.ro), pro_nudges=True)
        self.sent = []
        self.rt.send_host = lambda msg: self.sent.append(msg) or True
        self.rt.tact.on_sensor({"type": "front", "app": "Finder", "t": time.time() - 100})
        self.rt.tact.on_sensor({"type": "idle", "seconds": 30, "t": time.time()})
        self.w = self.rt.pro
        self.w.downloads = str(self.dl)
        self.w.free = lambda: 9 * 1024 ** 3

    def tearDown(self):
        self.p.stop()
        self.tmp.cleanup()

    def test_mini_has_no_watch_and_stage_api_is_closed(self):
        mini = pet.PetRuntime(home=str(self.ro), log_dir=str(self.ro / "logs"), edition="mini")
        self.assertIsNone(mini.pro)
        self.assertIsNone(mini.snapshot().get("pro"))

    def test_disk_low_toasts_once_a_day_with_a_fact(self):
        self.w.tick()
        toasts = [m for m in self.sent if m.get("cmd") == "toast"]
        self.assertEqual([t["trigger"] for t in toasts], ["disk_low"])
        self.assertEqual(toasts[0]["text"], "시동 디스크 남은 공간 9.0GB")
        self.w._last["disk"] = 0
        self.w.tick()
        self.assertEqual(len([m for m in self.sent if m.get("cmd") == "toast"]), 1)

    def test_installer_toast_accept_quarantines_one_and_card_can_undo(self):
        self.w.free = lambda: 100 * 1024 ** 3
        dmg = touch(self.dl / "Firefox 131.dmg", age=3600)
        (self.h / "Applications" / "Firefox.app").mkdir(parents=True)
        with mock.patch.object(scenarios, "installed_installers",
                               lambda d, app_dirs=None, now=None: [{"path": str(dmg), "app": "Firefox.app", "bytes": 1}]):
            self.w.tick()
        toast = next(m for m in self.sent if m.get("cmd") == "toast")
        self.assertEqual(toast["verb"], "설치 파일 격리")
        self.w._on_installer({"path": str(dmg)})
        self.assertFalse(dmg.exists())
        cid = self.rt.snapshot()["pro"]["card"]
        self.assertTrue(self.w.api({"op": "view", "id": cid})["card"]["applied"])
        self.assertTrue(self.w.api({"op": "undo", "id": cid})["ok"])
        self.assertTrue(dmg.exists())

    def test_promoted_installer_opens_card_without_moving(self):
        dmg = touch(self.dl / "Zoom.pkg", age=3600)
        self.w._on_installer({"path": str(dmg)}, promoted=True)
        self.assertTrue(dmg.exists())
        self.assertFalse(self.w.api({"op": "apply", "id": self.w.show, "picks": [1]})["ok"])   # 승인 없이 안 옮김

    def test_periodic_nudge_waits_for_a_pause_in_typing(self):
        now = time.time()
        self.rt.tact.on_sensor({"type": "idle", "seconds": 0.3, "t": now})
        self.w.tick(now)
        self.assertEqual([m for m in self.sent if m.get("cmd") == "toast"], [])
        self.assertIsNone(self.rt.snapshot()["hint"])                        # 1단계로 써 버리지 않는다
        self.rt.tact.on_sensor({"type": "idle", "seconds": 30, "t": now + 30})
        self.w.tick(now + 30)
        self.assertEqual([m["trigger"] for m in self.sent if m.get("cmd") == "toast"], ["disk_low"])

    def test_old_version_and_find_lost_from_ax(self):
        docs = self.h / "Docs"
        old = touch(docs / "보고서 v1.docx", age=86400 * 2)
        touch(docs / "보고서 v2.docx", age=86400)
        self.rt.tact.on_sensor({"type": "front", "app": "Pages", "t": time.time()})
        self.rt.on_host_line(json.dumps({"type": "ax", "event": "focused_window", "document": str(old)}))
        self.rt.on_host_line(json.dumps({"type": "ax", "event": "focused_window", "document": str(old)}))  # 한 번만
        toasts = [m for m in self.sent if m.get("cmd") == "toast"]
        self.assertEqual([t["trigger"] for t in toasts], ["old_version"])
        self.assertIn("보고서 v2.docx", toasts[0]["text"])
        # 찾기 헤맴은 하루 상한(1회)에 걸려 1단계(상태 줄)로 내려간다
        self.rt.tact.on_sensor({"type": "front", "app": "Finder", "t": time.time() - 60})
        for i, f in enumerate([self.dl, docs, self.dl, docs, self.h]):
            self.rt.on_host_line(json.dumps({"type": "ax", "event": "focused_window", "document": str(f)}))
        self.assertEqual(self.rt.snapshot()["hint"]["trigger"], "find_lost")

    def test_secret_front_app_drops_ax(self):
        self.rt.tact.on_sensor({"type": "front", "app": "1Password 8", "t": time.time()})
        before = len(self.sent)
        self.rt.on_host_line(json.dumps({"type": "ax", "event": "focused_window", "document": str(self.dl)}))
        self.assertEqual(len(self.sent), before)


if __name__ == "__main__":
    unittest.main()


class PetScriptOrderTest(unittest.TestCase):
    def test_native_host_flag_is_declared_before_first_use(self):
        # 2026-11-17: 269번 줄이 680번 줄 선언보다 먼저 읽어 펫 화면 스크립트 전체가 멈췄다(TDZ)
        src = (Path(pet.__file__).parent / "pet_ui" / "pet.js").read_text(encoding="utf-8")
        self.assertEqual(src.index("isNativeHost"), src.index("const isNativeHost") + len("const "))
