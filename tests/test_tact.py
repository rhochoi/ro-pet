import tempfile
import unittest
from pathlib import Path

from ro import config, designmetrics, tact

T0 = 1_800_000_000.0


class Clock:
    def __init__(self):
        self.t = T0

    def __call__(self):
        return self.t


class TactTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.home = Path(self.tmp.name) / "ro"
        self.log = str(Path(self.tmp.name) / "log")
        self.clock = Clock()
        self.g = tact.TactGate(self.home, self.log, self.clock)
        config.update(self.home, pro_nudges=True)
        self.g.on_sensor({"type": "front", "app": "Finder", "t": T0 - 100})
        self.g.on_sensor({"type": "idle", "seconds": 30, "t": T0})

    def tearDown(self):
        self.tmp.cleanup()

    def test_nothing_before_consent(self):
        config.update(self.home, pro_nudges=False)
        self.assertEqual(self.g.decide("dmg_installed")[0], tact.QUIET)

    def test_level2_when_calm(self):
        self.assertEqual(self.g.decide("dmg_installed"), (tact.LEVEL2, "조건 충족"))

    def test_secret_app_is_dropped_before_it_is_stored(self):
        self.assertFalse(self.g.on_sensor({"type": "front", "app": "1Password 8", "t": T0}))
        self.assertIsNone(self.g.front["app"])
        self.assertEqual(self.g.decide("find_lost")[0], tact.DROP)
        self.g.on_sensor({"type": "front", "app": "Safari", "window": "시크릿 브라우징", "t": T0})
        self.assertEqual(self.g.decide("find_lost")[0], tact.DROP)

    def test_busy_states_downgrade_to_level1(self):
        self.g.on_sensor({"type": "front", "app": "Keynote", "fullscreen": True, "t": T0})
        self.assertEqual(self.g.decide("dmg_installed"), (tact.LEVEL1, "전체 화면"))
        self.g.on_sensor({"type": "front", "app": "Finder", "t": T0})
        self.g.on_sensor({"type": "capture", "active": True, "t": T0})
        self.assertEqual(self.g.decide("dmg_installed")[1], "카메라·마이크 사용 중")
        self.g.on_sensor({"type": "capture", "active": False, "t": T0})
        self.g.on_sensor({"type": "idle", "seconds": 0.4, "t": T0})
        self.assertEqual(self.g.decide("dmg_installed")[1], "입력 중")
        self.clock.t += 4
        self.assertEqual(self.g.decide("dmg_installed")[1], "입력 중")  # 다음 보고 전까지는 입력 중으로 본다
        self.clock.t += 3                                      # 보고가 끊겼다 = 입력이 멈췄다
        self.assertEqual(self.g.decide("dmg_installed")[0], tact.LEVEL2)

    def test_seeking_is_dropped_while_user_organizes_or_launches_apps(self):
        dl = "/Users/x/Downloads"
        self.g.on_sensor({"type": "user_io", "path": dl + "/a.pdf", "t": T0 - 5})
        self.assertEqual(self.g.decide("find_lost", folder=dl), (tact.DROP, "직접 정리 중"))
        self.assertEqual(self.g.decide("find_lost", folder="/Users/x/Desktop")[0], tact.LEVEL2)
        self.g.on_sensor({"type": "front", "app": "Notes", "launched": True, "t": T0 - 3})
        self.assertEqual(self.g.decide("find_lost")[1], "앱 실행(런처)")
        self.clock.t += 30
        self.g.on_sensor({"type": "idle", "seconds": 30, "t": self.clock.t})
        self.assertEqual(self.g.decide("find_lost", folder=dl)[0], tact.LEVEL2)

    def test_daily_cap_and_backoff(self):
        self.g.record("dmg_installed", "shown")
        self.assertEqual(self.g.decide("old_version"), (tact.LEVEL1, "오늘 상한"))
        self.g.record("dmg_installed", "off")
        self.clock.t += 86400 + 60
        self.g.on_sensor({"type": "idle", "seconds": 30, "t": self.clock.t})
        self.assertEqual(self.g.decide("dmg_installed")[0], tact.LEVEL2)    # 1일 물러남 끝
        self.g.record("dmg_installed", "shown")
        self.g.record("dmg_installed", "ignored")
        self.clock.t += 2 * 86400
        self.g.on_sensor({"type": "idle", "seconds": 30, "t": self.clock.t})
        self.assertEqual(self.g.decide("dmg_installed"), (tact.LEVEL1, "물러나는 중"))  # 두 번째는 3일
        self.assertEqual(self.g.decide("old_version")[0], tact.LEVEL2)      # 다른 트리거는 별개

    def test_level1_exposure_does_not_count_toward_cap(self):
        self.g.record("dmg_installed", "shown", level=1)
        self.assertEqual(self.g.decide("dmg_installed")[0], tact.LEVEL2)

    def test_demoted_trigger_stays_level1(self):
        for _ in range(30):
            designmetrics.record_nudge("disk_low", "shown", log_dir=self.log, at=T0 - 3 * 86400)
        self.assertEqual(self.g.decide("disk_low"), (tact.LEVEL1, "강등된 트리거"))

    def test_bursts_are_merged_until_quiet(self):
        dl = "/Users/x/Downloads"
        for i in range(5):
            self.g.on_arrival(f"{dl}/photos/p{i}.jpg", now=T0 + i)
        self.g.on_arrival(f"{dl}/page.html", now=T0 + 2)
        self.g.on_arrival(f"{dl}/page_files/a.css", now=T0 + 3)
        self.assertEqual(self.g.flush(now=T0 + 10), [])
        out = {b["folder"]: b for b in self.g.flush(now=T0 + 20)}
        self.assertEqual(len(out[dl + "/photos"]["paths"]), 5)
        self.assertEqual(len(out[dl]["paths"]), 2)                         # html + _files 하나로
        self.assertEqual(self.g.flush(now=T0 + 40), [])


if __name__ == "__main__":
    unittest.main()
