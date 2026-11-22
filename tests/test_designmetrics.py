import tempfile
import time
import unittest
from pathlib import Path

from ro import designmetrics, log


class DesignMetricsTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.log = self.tmp.name
        self.now = time.time()

    def tearDown(self):
        self.tmp.cleanup()

    def add(self, kind, data, days_ago=0.0):
        log.append(kind, "요약", data, log_dir=self.log, at=self.now - days_ago * 86400)

    def test_counts_folded_vs_user_and_undo_within_week(self):
        self.add("organize", {"batch": "a", "count": 10, "categories": {"문서": 10},
                              "by_user": 2, "by_ro": 8, "by_unknown": 0}, days_ago=10)
        self.add("organize", {"batch": "a", "count": 3, "by_user": 0, "by_ro": 3, "by_unknown": 0}, days_ago=5)
        self.add("organize", {"batch": "old", "count": 4, "categories": {"사진": 4}}, days_ago=3)  # 기록 이전 형식
        self.add("organize_edit", {"from": "문서", "to": "계약"}, days_ago=10)
        self.add("organize_edit", {"from": "사진", "to": "사진"}, days_ago=10)
        m = designmetrics.compute(self.log, days=30, now=self.now)
        self.assertEqual((m["원칙2 ro가 접은 항목"], m["원칙2 사람이 고른 항목"]), (8, 2))
        self.assertEqual(m["원칙2 기록 이전 항목"], 4)
        self.assertEqual(m["원칙2 7일 안 되돌린 접힌 항목"], 3)
        self.assertEqual(m["원칙2 접힌 항목 되돌림 비율"], 0.375)
        self.assertEqual(m["원칙2 다르게 고른 비율"], 0.5)
        self.assertEqual(m["원칙4 ro를 부른 날"], 3)
        v = designmetrics.verdicts(m)
        self.assertEqual(v["원칙2 확신 기준"], "표본 부족")  # 접힌 항목 50개 전에는 판정하지 않는다
        self.assertEqual(v["원칙4 불림"], "반증 후보(다운로드 증가 여부 확인)")

    def test_undo_after_a_week_is_not_counted_and_window_limits_events(self):
        self.add("organize", {"batch": "b", "count": 60, "categories": {}, "by_user": 0, "by_ro": 60}, days_ago=20)
        self.add("organize", {"batch": "b", "count": 6, "by_user": 0, "by_ro": 6}, days_ago=10)
        self.add("note", {}, days_ago=40)  # 기간 밖
        m = designmetrics.compute(self.log, days=30, now=self.now)
        self.assertEqual(m["원칙2 7일 안 되돌린 접힌 항목"], 0)
        self.assertEqual(designmetrics.verdicts(m)["원칙2 확신 기준"], "통과")
        self.assertEqual(m["원칙4 ro를 부른 날"], 2)

    def test_downloads_counted_without_names(self):
        d = Path(self.tmp.name) / "dl"
        d.mkdir()
        (d / "비밀계획.pdf").write_text("x")
        m = designmetrics.compute(self.log, days=30, now=self.now, downloads=d)
        self.assertEqual(m["원칙4 다운로드 폴더 파일 수"], 1)
        self.assertNotIn("비밀계획", str(m))


    def nudge(self, trigger, action, n=1, batch=None, days_ago=1.0):
        for _ in range(n):
            designmetrics.record_nudge(trigger, action, batch=batch, log_dir=self.log,
                                       at=self.now - days_ago * 86400)

    def test_nudge_counts_and_undo_within_a_day(self):
        self.nudge("dmg_installed", "shown", 3)
        self.nudge("dmg_installed", "accepted", batch="b1", days_ago=2)
        self.nudge("dmg_installed", "accepted", batch="b2", days_ago=2)
        self.nudge("dmg_installed", "off")
        self.add("organize", {"batch": "b1", "count": 1, "by_ro": 1}, days_ago=1.9)   # 24시간 안 되돌림
        self.add("organize", {"batch": "b2", "count": 1, "by_ro": 1}, days_ago=0.5)   # 하루 넘어 되돌림
        c = designmetrics.nudges(self.log, days=30, now=self.now)["dmg_installed"]
        self.assertEqual((c["노출"], c["수락"], c["끄기"], c["24시간 안 되돌림"]), (3, 2, 1, 1))

    def test_trigger_demotes_after_30_shown_with_many_offs(self):
        self.nudge("old_version", "shown", 30)
        self.nudge("old_version", "accepted", 10)
        self.nudge("old_version", "off", 6)          # 20%
        self.nudge("disk_low", "shown", 30)
        self.nudge("disk_low", "accepted", 2)        # 수락 10% 미만
        self.nudge("find_lost", "shown", 30)
        self.nudge("find_lost", "accepted", 15)
        self.nudge("dmg_installed", "shown", 29)
        self.nudge("dmg_installed", "off", 29)       # 표본 부족이면 강등하지 않는다
        v = designmetrics.nudge_verdicts(designmetrics.nudges(self.log, now=self.now))
        self.assertEqual(v["old_version"], "1단계로 강등")
        self.assertEqual(v["disk_low"], "1단계로 강등")
        self.assertEqual(v["find_lost"], "유지")
        self.assertEqual(v["dmg_installed"], "표본 부족")
        self.assertTrue(designmetrics.demoted("disk_low", self.log, now=self.now))
        self.assertEqual(v["원칙4 전체"], "M5 목표 미달")   # 노출 119, 수락 27 → 도움률 23%

    def test_overall_reverts_when_acceptance_below_10_percent(self):
        self.nudge("find_lost", "shown", 100)
        self.nudge("find_lost", "accepted", 9)
        self.assertEqual(designmetrics.nudge_verdicts(designmetrics.nudges(self.log, now=self.now))["원칙4 전체"],
                         "개정 전으로 되돌리기 검토")

    def test_unknown_nudge_action_is_rejected(self):
        with self.assertRaises(ValueError):
            designmetrics.record_nudge("x", "clicked", log_dir=self.log)


if __name__ == "__main__":
    unittest.main()
