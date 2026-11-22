"""ro pro V2.1 실사용(Dogfood & Fix) 회귀 테스트 (DF-001 ~ DF-010)."""
import json
import os
import shutil
import tempfile
import time
import unittest
from pathlib import Path
from unittest import mock

from ro import cards, config, detect, find, journal, organize, pet, profile, scenarios, staging


class ProDogfoodRegressionTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.h = Path(self.tmp.name).resolve() / "home"
        self.ro = self.h / ".ro"
        self.dl = self.h / "Downloads"
        self.docs = self.h / "Documents"
        self.apps = self.h / "Applications"
        self.projects = self.h / "Projects"
        for d in (self.ro, self.dl, self.docs / "가_임시", self.docs / "하반기_계약", self.docs / "정리됨", self.apps, self.projects):
            d.mkdir(parents=True, exist_ok=True)
        self.p_home = mock.patch("pathlib.Path.home", return_value=self.h)
        self.p_home.start()
        self.env = mock.patch.dict(os.environ, {"HOME": str(self.h), "RO_HOME": str(self.ro), "RO_EDITION": "pro"})
        self.env.start()

    def tearDown(self):
        self.env.stop()
        self.p_home.stop()
        self.tmp.cleanup()

    def _touch(self, p: Path, content: str, age_days: float = 10.0):
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(content, encoding="utf-8")
        t = time.time() - age_days * 86400
        os.utime(p, (t, t))
        return p

    def test_df001_profile_prior_wires_into_organize_and_find(self):
        now = time.time()
        target = self.docs / "하반기_계약"
        self._touch(self.dl / "보고서_요약.pdf", "summary pdf")
        self._touch(self.docs / "가_임시" / "분기_보고서.pdf", "report a")
        self._touch(target / "분기_보고서.pdf", "report b")

        profile.set_consent(str(self.ro), True)
        for d in (3, 2, 1):
            profile.observe("ext_home", ".pdf", str(target), home=str(self.ro), now=now - d * 86400)
            profile.observe("pick_folder", ".pdf", str(target), home=str(self.ro), now=now - d * 86400)

        plan = organize.scan(root=str(self.dl), dest_root=str(self.docs / "정리됨"), home=str(self.ro))
        pdf_item = next(i for i in plan["items"] if Path(i["path"]).name == "보고서_요약.pdf")
        self.assertEqual(Path(pdf_item["dest"]).parent.resolve(), target.resolve())

        res = find.search("분기 보고서", roots=[str(self.docs)], spotlight=False, home=str(self.ro))
        self.assertEqual(Path(res["results"][0]["path"]).parent.resolve(), target.resolve())
        self.assertIn("자주 쓰는 폴더", res["results"][0]["reasons"])

    def test_df002_cards_moved_history_and_minhash_related_wire_into_find(self):
        now = time.time()
        body = (
            "로컬 우선 파일 지능 아키텍처 설계 문서입니다. 원본 데이터는 절대 기기 밖으로 보내지 않습니다. "
            "파일 카드는 아이노드와 해시 그리고 단어 삼그램 기반 민해시 서명을 사용하여 경로가 바뀌거나 이름이 변경되어도 "
            "같은 문서 계열과 유사 판본을 추적합니다. 검색과 정리 단계에서 이전 이름과 관련 문서 이력을 활용합니다. "
            "저널 버전 투는 모든 이동을 원자적으로 기록하고 한 번의 클릭으로 원래 상태를 복원합니다."
        )
        old_p = self._touch(self.docs / "가_임시" / "구버전_전략서.md", body, age_days=15)
        sim_p = self._touch(self.docs / "하반기_계약" / "유사_발표본.md", body + " 추가 개정 내용입니다.", age_days=3)
        roots = [str(self.docs)]
        cards.scan(roots=roots, home=str(self.ro), now=now - 3600)
        new_p = self.docs / "하반기_계약" / "신규_전략문서.md"
        shutil.move(str(old_p), str(new_p))
        cards.scan(roots=roots, home=str(self.ro), now=now)

        r_old = find.search("구버전_전략서", roots=roots, spotlight=False, home=str(self.ro))
        self.assertIn(new_p.resolve(), [Path(x["path"]).resolve() for x in r_old["results"]])

        r_sim = find.search("신규_전략문서", roots=roots, spotlight=False, home=str(self.ro))
        related_paths = [Path(s["path"]).resolve() for s in r_sim["results"][0].get("related", [])]
        self.assertIn(sim_p.resolve(), related_paths)

    def test_df003_ready_event_exposes_ax_status_and_swift_subscribes_title_change(self):
        swift = (Path(pet.__file__).parent / "pet_mac.swift").read_text(encoding="utf-8")
        self.assertIn("kAXTitleChangedNotification", swift)
        self.assertGreaterEqual(swift.count("AXIsProcessTrusted"), 2)
        self.assertIn('"--sensor"', swift)
        self.assertIn('"--no-kill"', swift)

        rt = pet.PetRuntime(home=str(self.ro), log_dir=str(self.ro / "logs"), edition="pro")
        self.assertTrue(rt.on_host_line(json.dumps({"type": "ready", "ax": False, "t": time.time()})))
        self.assertIs(rt.snapshot()["pro"]["ax"], False)
        self.assertTrue(rt.on_host_line(json.dumps({"type": "ready", "ax": True, "t": time.time()})))
        self.assertIs(rt.snapshot()["pro"]["ax"], True)

    def test_df004_and_df005_on_demand_disk_and_organize_stage_cards_with_undo(self):
        now = time.time()
        # Dead build (>10MB) + >15GB free disk
        proj = self.projects / "old-proj"
        self._touch(proj / "pyproject.toml", "[project]\nname='old'\n", age_days=120)
        blob = proj / ".venv" / "data.bin"
        blob.parent.mkdir(parents=True, exist_ok=True)
        blob.write_bytes(b"A" * (11 * 1024 * 1024))
        self._touch(self.dl / "메모.md", "테스트 문서 본문입니다.\n" * 5, age_days=10)
        config.update(str(self.ro), roots=[str(self.projects)], profile_learning=True)

        rt = pet.PetRuntime(home=str(self.ro), log_dir=str(self.ro / "logs"), edition="pro")
        rt.pro.free = lambda: 200 * 1024 ** 3
        rt.pro.downloads = str(self.dl)

        # DF-004: on-demand disk card works despite 200GB free
        disk_res = rt.pro.api({"op": "disk"})
        self.assertTrue(disk_res["ok"])
        self.assertTrue(any(".venv" in it["name"] for it in disk_res["card"]["items"]))

        # DF-005: on-demand organize C-plan card applies via Journal V2 and undoes cleanly
        org_res = rt.pro.api({"op": "organize", "root": str(self.dl), "dest_root": str(self.docs / "정리됨")})
        self.assertTrue(org_res["ok"])
        cid = org_res["card"]["id"]
        picks = [org_res["card"]["items"][0]["id"]]
        ap = rt.pro.api({"op": "apply", "id": cid, "picks": picks, "approve": True})
        self.assertTrue(ap["ok"] and ap["moved"] == 1 and ap["undo"])
        self.assertTrue(journal.read(str(self.ro)))
        un = rt.pro.api({"op": "undo", "id": cid})
        self.assertTrue(un["ok"] and un["files"] == 1)
        self.assertTrue((self.dl / "메모.md").exists())

    def test_df006_korean_version_names_group_and_trigger_newer_version(self):
        v1 = self._touch(self.dl / "계약서_v1.md", "v1", age_days=30)
        v2 = self._touch(self.dl / "계약서_최종_v2.md", "v2", age_days=5)
        v2c = self._touch(self.dl / "계약서_최종_v2(1).md", "v2", age_days=4)
        groups = detect.version_groups([(p, p.stat()) for p in (v1, v2, v2c)])
        self.assertEqual(len(groups), 1)
        self.assertEqual(groups[0][0][0], v2)
        self.assertEqual(scenarios.newer_version(v1), str(v2))

    def test_df007_dmg_drag_install_with_preserved_build_mtime(self):
        now = time.time()
        dmg = self.dl / "DummyApp-2.1-arm64.dmg"
        dmg.write_bytes(b"dmg")
        os.utime(dmg, (now - 3600, now - 3600))
        app = self.apps / "DummyApp.app"
        (app / "Contents").mkdir(parents=True)
        (app / "Contents" / "Info.plist").write_text("<plist/>", encoding="utf-8")
        old_build = now - 30 * 86400
        os.utime(app, (old_build, old_build))
        hits = scenarios.installed_installers(str(self.dl), app_dirs=(str(self.apps),), now=now)
        self.assertEqual([h["path"] for h in hits], [str(dmg)])

    def test_df008_pre_consent_tick_does_not_lock_out_post_consent_nudges(self):
        now = time.time()
        config.update(str(self.ro), pro_nudges=False)
        rt = pet.PetRuntime(home=str(self.ro), log_dir=str(self.ro / "logs"), edition="pro")
        rt.pro.downloads = str(self.dl)
        rt.pro.free = lambda: 5 * 1024 ** 3
        sent = []
        rt.send_host = lambda m: sent.append(m) or True
        rt.pro.tick(now=now)
        self.assertEqual(sent, [])
        config.update(str(self.ro), pro_nudges=True)
        rt.pro.tick(now=now + 700)
        self.assertEqual([m["trigger"] for m in sent if m.get("cmd") == "toast"], ["disk_low"])

    def test_df009_and_df010_level1_hint_accept_and_ax_timestamp_forwarding(self):
        now = time.time()
        config.update(str(self.ro), pro_nudges=True)
        rt = pet.PetRuntime(home=str(self.ro), log_dir=str(self.ro / "logs"), edition="pro")
        # DF-009: LEVEL1 hint accepted via API
        dec, _ = rt.nudge("find_lost", "2분 동안 폴더를 4번 오가셨어요", "파일 찾기", data={}, now=now)
        self.assertEqual(dec, "level1")
        self.assertTrue(rt.pro.api({"op": "hint_accept"})["ok"])
        self.assertIsNone(rt.snapshot()["hint"])
        # DF-010: AX timestamp forwarding prevents false find_lost across 400s
        sent = []
        rt.send_host = lambda m: sent.append(m) or True
        rt.on_host_line(json.dumps({"type": "front", "app": "Finder", "t": now - 500}))
        for i, d in enumerate((self.dl, self.docs, self.apps, self.projects, self.docs / "가_임시")):
            rt.on_host_line(json.dumps({"type": "ax", "event": "title_changed", "document": str(d), "t": now - 500 + i * 100}))
        self.assertEqual([m for m in sent if m.get("trigger") == "find_lost"], [])

    def test_df011_log_respects_ro_home_and_pet_passes_log_dir(self):
        from ro import log
        log.append("eval", "iso check", {})
        self.assertTrue(list((self.ro / "log").glob("*.jsonl")))
        src = Path(pet.__file__).read_text(encoding="utf-8")
        self.assertIn('log.append("pet", "라이선스를 받아 pro로 다시 시작", {}, log_dir=self.log_dir)', src)


if __name__ == "__main__":
    unittest.main()
