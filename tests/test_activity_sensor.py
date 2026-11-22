import time
import unittest
from unittest import mock

from ro import activity


class SensorPushTest(unittest.TestCase):
    def tearDown(self):
        activity.SENSOR.clear()

    def test_fresh_sensor_replaces_subprocess_polling(self):
        now = time.time()
        activity.push({"type": "front", "app": "Claude", "t": now})
        activity.push({"type": "idle", "seconds": 1.0, "t": now})
        runner = mock.Mock(side_effect=AssertionError("subprocess"))
        with mock.patch("ro.handoff.front_app", side_effect=AssertionError("lsappinfo")):
            ev = activity.observe(runner, now + 1)
        self.assertEqual(ev["app"], "Claude")
        runner.assert_not_called()

    def test_excluded_app_from_sensor_is_never_stored(self):
        now = time.time()
        activity.push({"type": "front", "app": "1Password 8", "t": now})
        activity.push({"type": "idle", "seconds": 1.0, "t": now})
        self.assertIsNone(activity.SENSOR["app"][0])
        self.assertIsNone(activity.observe(mock.Mock(side_effect=AssertionError), now))

    def test_stale_sensor_falls_back_to_polling(self):
        old = time.time() - 3600
        activity.push({"type": "front", "app": "Claude", "t": old})
        runner = mock.Mock(return_value=mock.Mock(returncode=0, stdout='"HIDIdleTime" = 999999999999', stderr=""))
        self.assertEqual(activity.observe(runner, time.time()), {"t": mock.ANY, "idle": True})
        runner.assert_called()


if __name__ == "__main__":
    unittest.main()
