"""ro pro V2.1 M4 회귀: 엣지케이스 18개 강제 계약 + mini 무접촉 + 동시 쓰기 + 중단 복구.

번호는 청사진 §5.2(6묶음)를 하나씩 풀어 쓴 것이다. 같은 규칙을 모듈 단위로 더 자세히 보는 테스트는
test_fsguard·test_journal·test_tact·test_scenarios에 있고, 여기서는 ro pro가 실제로 지나가는 길(확인 카드·저널·
TactGate·펫 런타임)로 한 번씩 확인한다.
"""
import json
import os
import sqlite3
import subprocess
import sys
import tempfile
import time
import unittest
import unicodedata
from pathlib import Path
from types import SimpleNamespace
from unittest import mock

from ro import cards, config, designmetrics, fsguard, journal, pet, profile, scenarios, staging, tact

DAY = 86400


def touch(p, age=3600.0, text="x"):
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(text)
    t = time.time() - age
    os.utime(p, (t, t))
    return p


class Home(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.h = Path(self.tmp.name).resolve() / "home"
        self.dl = self.h / "Downloads"
        self.docs = self.h / "Documents"
        self.dl.mkdir(parents=True)
        self.docs.mkdir()
        self.ro = self.h / ".ro"
        self.log = str(self.ro / "log")
        self.p = mock.patch("pathlib.Path.home", return_value=self.h)
        self.p.start()
        self.calls = []
        self.stage = staging.Stage(self.ro, self.log, runner=self.fake_run)

    def tearDown(self):
        self.p.stop()
        self.tmp.cleanup()

    def fake_run(self, args, **kw):
        self.calls.append(args)
        return SimpleNamespace(returncode=0, stdout="", stderr="")

    def card(self, *items, roots=None):
        return self.stage.open("disk", "disk_low", list(items), roots or [self.dl, self.docs], "t")

    def trust(self, n):
        for _ in range(n):
            designmetrics.record_nudge("dmg_installed", "accepted", log_dir=self.log)


class DatalessAndPackages(Home):
    # 1~4: iCloud에만 있는 파일, 패키지
    def test_01_materialization_is_off_in_the_process(self):
        self.assertEqual(fsguard.materialization_policy(), 1)

    def test_02_dataless_file_is_never_opened_or_moved_by_a_card(self):
        f = touch(self.dl / "cloud.pdf")
        cid = self.card(staging.item("quarantine", f, 0.95, "x"))
        with mock.patch.object(fsguard, "is_dataless", lambda p, st=None: True), \
                mock.patch("builtins.open", side_effect=AssertionError("열지 않는다")):
            res = self.stage.apply(cid, [1], approve=True)
        self.assertEqual(res["moved"], [])
        self.assertTrue(f.exists())

    def test_03_cross_volume_is_refused_without_copy(self):
        f = touch(self.dl / "a.pdf")
        with mock.patch.object(journal.os, "replace", side_effect=OSError(journal.errno.EXDEV, "x")), \
                mock.patch("shutil.copy2", side_effect=AssertionError("복사하지 않는다")):
            res = self.stage.apply(self.card(staging.item("quarantine", f, 0.95, "x")), [1], approve=True)
        self.assertIn("다른 볼륨", res["skipped"][0][1])
        self.assertTrue(f.exists())

    def test_04_meta_only_judgement_is_capped_and_not_preselected(self):
        f = touch(self.dl / "big.mov")
        view = self.stage.view(self.card(staging.item("evict", f, 1.0, "x")))
        self.assertEqual((view["items"][0]["confidence"], view["items"][0]["sure"]), (0.75, False))

    def test_05_packages_are_one_item_and_never_walked_into(self):
        (self.dl / "Deck.key" / "Data").mkdir(parents=True)
        touch(self.dl / "Deck.key" / "Data" / "secret.txt")
        out = [(p.name, k) for p, _, k in fsguard.walk(self.dl)]
        self.assertEqual(out, [("Deck.key", "package")])

    def test_06_structure_of_obsidian_and_vscode_folders_is_not_rearranged(self):
        self.trust(5)
        f = touch(self.dl / "a.md")
        (self.docs / "vault" / ".obsidian").mkdir(parents=True)
        cid = self.stage.open("assist", "assist", [staging.item("move", f, 0.95, "x", dest=self.docs / "vault")],
                              [self.dl, self.docs], "t")
        res = self.stage.apply(cid, [1], approve=True)
        self.assertIn("구조를 바꾸지 않는", res["skipped"][0][1])
        self.assertTrue(f.exists())


class EditingAndPermissions(Home):
    # 7~10: 편집 중·잠금·방금 바뀜·권한·열린 문서
    def test_07_lock_files_and_files_with_lock_siblings_are_held(self):
        f = touch(self.dl / "report.docx")
        touch(self.dl / "~$report.docx")
        res = self.stage.apply(self.card(staging.item("quarantine", f, 0.95, "x")), [1], approve=True)
        self.assertEqual(res["skipped"][0][1], "편집 중")

    def test_08_files_changed_in_the_last_two_minutes_are_held(self):
        f = touch(self.dl / "fresh.zip", age=10)
        res = self.stage.apply(self.card(staging.item("quarantine", f, 0.95, "x")), [1], approve=True)
        self.assertEqual(res["skipped"][0][1], "방금 바뀜")

    def test_09_document_open_in_the_front_window_is_held(self):
        f = touch(self.dl / "draft.pages")
        self.stage.open_docs[str(f)] = time.time() - 60
        res = self.stage.apply(self.card(staging.item("quarantine", f, 0.95, "x")), [1], approve=True)
        self.assertEqual(res["skipped"][0][1], "열려 있음")

    def test_10_read_only_folder_is_held(self):
        ro_dir = self.dl / "잠긴"
        f = touch(ro_dir / "a.pdf")
        os.chmod(ro_dir, 0o500)
        try:
            res = self.stage.apply(self.card(staging.item("quarantine", f, 0.95, "x")), [1], approve=True)
        finally:
            os.chmod(ro_dir, 0o700)
        self.assertEqual(res["skipped"][0][1], "쓰기 권한 없음")


class BurstsNamesAndCollisions(Home):
    # 11~13: 묶음 유입·이름 정규화·충돌
    def test_11_bursts_and_saved_web_pages_become_one_event(self):
        g = tact.TactGate(self.ro, self.log, clock=lambda: 0)
        for i in range(30):
            g.on_arrival(f"{self.dl}/unzipped/p{i}.jpg", now=i * 0.3)
        g.on_arrival(f"{self.dl}/page.html", now=1)
        g.on_arrival(f"{self.dl}/page_files/x.js", now=2)
        self.assertEqual(g.flush(now=12), [])
        self.assertEqual(sorted(len(b["paths"]) for b in g.flush(now=30)), [2, 30])

    def test_12_names_compare_after_unquote_nfc_and_case_fold(self):
        nfd = unicodedata.normalize("NFD", "보고서 최종.pdf")
        self.assertEqual(fsguard.name_key(nfd), fsguard.name_key("보고서%20최종.PDF"))

    def test_13_case_only_collision_is_refused_and_nothing_is_overwritten(self):
        self.trust(5)
        f = touch(self.dl / "Report.pdf", text="new")
        old = touch(self.docs / "report.pdf", text="old")
        cid = self.stage.open("assist", "assist", [staging.item("move", f, 0.95, "x", dest=self.docs)],
                              [self.dl, self.docs], "t")
        res = self.stage.apply(cid, [1], approve=True)
        self.assertEqual(res["moved"], [])
        self.assertEqual(old.read_text(), "old")
        self.assertTrue(f.exists())


class JournalRecovery(Home):
    # 14~15: 저널 V2 역순 되돌리기·크래시 복구
    def test_14_undo_restores_in_reverse_and_leaves_things_changed_since(self):
        a, b = touch(self.dl / "a.dmg"), touch(self.dl / "b.dmg")
        cid = self.card(staging.item("quarantine", a, 0.95, "x"), staging.item("quarantine", b, 0.95, "x"))
        self.stage.apply(cid, [1, 2], approve=True)
        moved_b = next((self.ro / "cleanup" / "trash").rglob("*b.dmg"))
        moved_b.unlink()
        touch(moved_b, text="다른 파일")                      # 그 사이 바뀜(다른 inode)
        res = self.stage.undo(cid)
        self.assertTrue(a.exists())
        self.assertFalse(b.exists())
        self.assertIn("b.dmg", str(res["skipped"][0][0]))             # 바뀐 파일과 그 상자 폴더는 그대로 둔다

    def test_15_killed_mid_batch_is_recovered_when_the_pro_pet_starts(self):
        a, b = touch(self.dl / "a.dmg"), touch(self.dl / "b.dmg")
        trash = self.ro / "cleanup" / "trash"
        trash.mkdir(parents=True)
        bt = journal.Batch("stage-disk", [self.dl, trash], self.ro).__enter__()   # commit 전에 죽는다(SIGKILL)
        bt.mkdir(trash / bt.id)
        bt.move(a, trash / bt.id / "1-a.dmg")
        self.assertFalse(a.exists())
        rt = pet.PetRuntime(home=str(self.ro), log_dir=self.log, edition="pro")
        self.assertEqual(len(rt.pro.recovered), 1)
        self.assertTrue(a.exists() and b.exists())
        self.assertIn("되돌렸어요", rt.pro.snapshot()["notice"])
        self.assertEqual(journal.recover(self.ro), [])

    def test_15b_ctrl_c_inside_a_batch_rolls_back_at_once(self):
        a, b = touch(self.dl / "a.dmg"), touch(self.dl / "b.dmg")
        cid = self.card(staging.item("quarantine", a, 0.95, "x"), staging.item("quarantine", b, 0.95, "x"))
        real = journal.Batch.move
        calls = []

        def interrupt_second(self_, src, dst):
            calls.append(src)
            if len(calls) == 2:
                raise KeyboardInterrupt
            return real(self_, src, dst)
        with mock.patch.object(journal.Batch, "move", interrupt_second):
            with self.assertRaises(KeyboardInterrupt):
                self.stage.apply(cid, [1, 2], approve=True)
        self.assertTrue(a.exists() and b.exists())
        self.assertEqual(journal.recover(self.ro), [])


class FalsePositives(Home):
    # 16~18: 오탐 억제
    def gate(self):
        config.update(self.ro, pro_nudges=True)
        g = tact.TactGate(self.ro, self.log)
        g.on_sensor({"type": "front", "app": "Finder", "t": time.time() - 100})
        g.on_sensor({"type": "idle", "seconds": 30, "t": time.time()})
        return g

    def test_16_user_organizing_or_launching_apps_drops_seeking(self):
        g = self.gate()
        g.on_sensor({"type": "user_io", "path": str(self.dl / "a.pdf"), "t": time.time() - 5})
        self.assertEqual(g.decide("find_lost", folder=str(self.dl))[0], tact.DROP)
        g = self.gate()
        g.on_sensor({"type": "front", "app": "Notes", "launched": True, "t": time.time() - 2})
        self.assertEqual(g.decide("find_lost")[1], "앱 실행(런처)")

    def test_17_fullscreen_camera_and_typing_lower_to_level1(self):
        for ev, why in (({"type": "fullscreen", "active": True}, "전체 화면"),
                        ({"type": "capture", "active": True}, "카메라·마이크 사용 중"),
                        ({"type": "idle", "seconds": 0.2}, "입력 중")):
            g = self.gate()
            g.on_sensor({**ev, "t": time.time()})
            self.assertEqual(g.decide("dmg_installed"), (tact.LEVEL1, why))

    def test_18_secret_apps_are_dropped_before_anything_is_stored(self):
        rt = pet.PetRuntime(home=str(self.ro), log_dir=self.log, edition="pro")
        profile.set_consent(self.ro)
        config.update(self.ro, pro_nudges=True)
        with mock.patch.dict(os.environ, {"RO_EDITION": "pro"}):
            rt.on_host_line(json.dumps({"type": "front", "app": "1Password 8", "t": time.time()}))
            rt.on_host_line(json.dumps({"type": "front", "app": "Safari", "window": "시크릿 브라우징", "t": time.time()}))
        self.assertIsNone(rt.tact.front["app"])
        self.assertFalse(profile.db_path(self.ro).exists())
        self.assertEqual(rt.tact.decide("find_lost")[1], "비밀 앱")


class MiniNoContact(Home):
    """mini: 센서·토스트·⌥R·확인 카드·학습 DB·카드 색인을 만들지도 부르지도 않는다."""

    def test_mini_runtime_creates_nothing_pro(self):
        config.update(self.ro, pro_nudges=True, profile_learning=True)
        with mock.patch.dict(os.environ, {"RO_EDITION": "mini"}):
            rt = pet.PetRuntime(home=str(self.ro), log_dir=self.log)
            self.assertEqual(rt.edition, "mini")
            self.assertIsNone(rt.tact)
            self.assertIsNone(rt.pro)
            self.assertFalse(rt.on_host_line('{"type": "front", "app": "Finder"}'))
            self.assertEqual(rt.nudge("disk_low", "남은 공간 9GB", "보기"), ("quiet", None))
            self.assertFalse(rt.send_host({"cmd": "toast"}))
            self.assertFalse(rt.learned_api({"op": "list"})["ok"])
            rt.attach_host(object())
            self.assertIsNone(rt._host_in)
        for name in ("memory.db", "cards.db", "journal.jsonl"):
            self.assertFalse((self.ro / name).exists(), name)

    def test_mini_server_closes_pro_routes(self):
        from urllib.error import HTTPError
        from urllib.request import Request, urlopen
        rt = pet.PetRuntime(home=str(self.ro), log_dir=self.log, edition="mini")
        srv = pet.start_server(rt, "127.0.0.1", 0)
        try:
            port = srv.server_address[1]
            for path in ("/api/stage", "/api/memory", "/api/find"):
                req = Request(f"http://127.0.0.1:{port}{path}", data=b"{}", method="POST",
                              headers={"X-Ro-Token": rt.token, "Content-Type": "application/json"})
                with self.assertRaises(HTTPError) as ctx:
                    urlopen(req, timeout=3)
                self.assertEqual(ctx.exception.code, 403, path)
        finally:
            srv.shutdown()
            srv.server_close()

    def test_mini_host_launch_has_no_pipe_or_sensor(self):
        src = (Path(pet.__file__).parent / "pet_mac.swift").read_text(encoding="utf-8")
        self.assertIn("delegate.proSensor = proArg && !miniArg", src)
        launch = Path(pet.__file__).read_text(encoding="utf-8").split("def launch(", 1)[1]
        mini_branch = launch.split('cmd.append("--mini")', 1)[1].split("else:", 1)[0]
        self.assertIn("subprocess.Popen(cmd)", mini_branch)                 # 파이프 없음
        self.assertNotIn("prowatch", mini_branch)

    def test_mini_cli_refuses_pro_commands(self):
        env = {**os.environ, "HOME": str(self.h), "RO_EDITION": "mini"}
        for args in (["learned"], ["cards", "report"], ["storage", "builds"]):
            r = subprocess.run([sys.executable, "-m", "ro", *args], env=env, capture_output=True, text=True,
                               cwd=str(Path(pet.__file__).parent.parent), timeout=60)
            self.assertNotEqual(r.returncode, 0, args)
        self.assertFalse((self.ro / "memory.db").exists())
        self.assertFalse((self.ro / "cards.db").exists())


class Concurrency(Home):
    """SQLITE_BUSY: 다른 쓰기가 잠금을 쥐고 있어도 펫이 멈추거나 죽지 않는다."""

    def test_profile_write_gives_up_quietly_when_locked(self):
        profile.set_consent(self.ro)
        profile.observe("ext_home", ".pdf", self.docs, home=self.ro)
        other = sqlite3.connect(profile.db_path(self.ro))
        other.execute("BEGIN IMMEDIATE")
        try:
            with mock.patch.object(profile, "BUSY_MS", 100), mock.patch.dict(os.environ, {"RO_EDITION": "pro"}):
                t0 = time.monotonic()
                self.assertFalse(profile.observe_quiet("ext_home", ".hwp", self.docs, home=self.ro))
                self.assertLess(time.monotonic() - t0, 2)
        finally:
            other.rollback()
            other.close()
        with mock.patch.dict(os.environ, {"RO_EDITION": "pro"}):
            self.assertTrue(profile.observe_quiet("ext_home", ".hwp", self.docs, home=self.ro))   # 풀리면 다시 쓴다

    def test_cards_readers_work_while_the_indexer_writes(self):
        touch(self.dl / "a.pdf", text="hello world foo bar")
        cards.scan(roots=[self.dl], home=self.ro)
        writer = cards.connect(self.ro)
        writer.execute("BEGIN IMMEDIATE")
        try:
            reader = cards.connect(self.ro, read_only=True)
            n = reader.execute("SELECT count(*) FROM cards").fetchone()[0]
            reader.close()
        finally:
            writer.rollback()
            writer.close()
        self.assertEqual(n, 1)


class KillSwitch(Home):
    """M5: 트리거별 강등과 원칙 4 전체 킬스위치가 실제로 2단계를 막는다."""

    def gate(self):
        config.update(self.ro, pro_nudges=True)
        g = tact.TactGate(self.ro, self.log)
        g.on_sensor({"type": "front", "app": "Finder", "t": time.time() - 100})
        g.on_sensor({"type": "idle", "seconds": 30, "t": time.time()})
        return g

    def test_card_undo_counts_as_undone_within_a_day(self):
        at = time.time() - 3600
        designmetrics.record_nudge("disk_low", "shown", log_dir=self.log, at=at)
        designmetrics.record_nudge("disk_low", "accepted", log_dir=self.log, at=at + 5)
        designmetrics.record_nudge("disk_low", "undone", log_dir=self.log, at=at + 600)
        self.assertEqual(designmetrics.nudges(self.log)["disk_low"]["24시간 안 되돌림"], 1)

    def test_overall_kill_switch_turns_every_trigger_to_level1(self):
        at = time.time() - 2 * DAY
        for i in range(100):
            designmetrics.record_nudge(("disk_low", "old_version")[i % 2], "shown", log_dir=self.log, at=at)
        for _ in range(5):
            designmetrics.record_nudge("disk_low", "accepted", log_dir=self.log, at=at)
        self.assertTrue(designmetrics.kill_switch(self.log))
        self.assertEqual(self.gate().decide("dmg_installed"), (tact.LEVEL1, "원칙4 킬스위치"))

    def test_learned_card_reports_metrics(self):
        at = time.time() - DAY
        for _ in range(30):
            designmetrics.record_nudge("dmg_installed", "shown", log_dir=self.log, at=at)
        for _ in range(10):
            designmetrics.record_nudge("dmg_installed", "off", log_dir=self.log, at=at)
        rt = pet.PetRuntime(home=str(self.ro), log_dir=self.log, edition="pro")
        m = rt.learned_api({"op": "list"})["metrics"]
        self.assertEqual((m["shown"], m["off"], m["demoted"]), (30, 0.33, ["dmg_installed"]))


if __name__ == "__main__":
    unittest.main()
