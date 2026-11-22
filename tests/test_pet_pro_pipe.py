import io
import json
import tempfile
import time
import unittest
from pathlib import Path

from ro import activity, config, pet, tact


class ProPipeTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        t = Path(self.tmp.name)
        self.kw = dict(home=str(t / "ro"), log_dir=str(t / "log"), map_path=str(t / "m.json"))

    def tearDown(self):
        activity.SENSOR.clear()
        self.tmp.cleanup()

    def test_mini_has_no_gate_no_pipe_and_ignores_host_lines(self):
        rt = pet.PetRuntime(edition="mini", **self.kw)
        self.assertIsNone(rt.tact)
        rt.attach_host(io.StringIO())
        self.assertFalse(rt.send_host({"cmd": "toast"}))
        self.assertFalse(rt.on_host_line(json.dumps({"type": "front", "app": "Finder"})))
        self.assertEqual(activity.SENSOR, {})
        self.assertFalse(Path(self.kw["home"], "cards.db").exists())

    def test_pro_routes_sensor_lines_and_toast_results(self):
        rt = pet.PetRuntime(edition="pro", **self.kw)
        out = io.StringIO()
        rt.attach_host(out)
        self.assertTrue(rt.on_host_line(json.dumps({"type": "front", "app": "Finder", "t": time.time()})))
        self.assertEqual(rt.tact.front["app"], "Finder")
        self.assertEqual(activity.SENSOR["app"][0], "Finder")
        self.assertFalse(rt.on_host_line("not json"))
        self.assertFalse(rt.on_host_line(json.dumps({"type": "keylog", "keys": "x"})))
        self.assertTrue(rt.send_host({"cmd": "toast", "id": "t1"}))
        self.assertEqual(json.loads(out.getvalue())["cmd"], "toast")
        self.assertFalse(rt.on_host_line(json.dumps({"type": "toast_result", "id": "x", "trigger": "dmg_installed",
                                                     "action": "off"})))   # 띄운 적 없는 토스트

    def calm(self, rt):
        config.update(rt.home, pro_nudges=True)
        rt.on_host_line(json.dumps({"type": "idle", "seconds": 60, "t": time.time()}))

    def test_nudge_shows_toast_and_off_silences_the_type(self):
        rt = pet.PetRuntime(edition="pro", **self.kw)
        out = io.StringIO()
        rt.attach_host(out)
        self.calm(rt)
        decision, nid = rt.nudge("dmg_installed", "설치 끝 · Foo.dmg 1.2GB", "격리")
        self.assertEqual(decision, tact.LEVEL2)
        msg = json.loads(out.getvalue())
        self.assertEqual((msg["cmd"], msg["id"], msg["verb"]), ("toast", nid, "격리"))
        self.assertTrue(rt.on_host_line(json.dumps({"type": "toast_result", "id": nid, "trigger": "dmg_installed",
                                                    "action": "off"})))
        self.assertEqual(rt.tact.decide("dmg_installed"), (tact.QUIET, "꺼 둔 유형"))
        self.assertFalse(rt.on_host_line(json.dumps({"type": "toast_result", "id": nid, "trigger": "dmg_installed",
                                                     "action": "accepted"})))  # 같은 결과를 두 번 받지 않는다

    def test_accept_and_promote_call_the_registered_handler(self):
        rt = pet.PetRuntime(edition="pro", **self.kw)
        rt.attach_host(io.StringIO())
        self.calm(rt)
        got = []
        done = __import__("threading").Event()
        rt.nudge_handlers["old_version"] = lambda data, promoted: (got.append((data, promoted)), done.set())
        _, nid = rt.nudge("old_version", "3일 전 더 최신 판이 있음", "최신 판 열기", data={"card": 7})
        rt.on_host_line(json.dumps({"type": "toast_result", "id": nid, "trigger": "old_version", "action": "promote"}))
        done.wait(2)
        self.assertEqual(got, [({"card": 7}, True)])

    def test_question_or_nagging_text_is_refused(self):
        rt = pet.PetRuntime(edition="pro", **self.kw)
        for bad in ("정리해 드릴까요?", "아직 안 하셨어요", "Want me to tidy up", "두 줄\n문구"):
            with self.assertRaises(ValueError):
                rt.nudge("find_lost", bad, "보기")

    def test_without_host_it_falls_back_to_status_line_hint(self):
        rt = pet.PetRuntime(edition="pro", **self.kw)
        self.calm(rt)
        decision, nid = rt.nudge("disk_low", "남은 공간 9GB", "용량 보기")
        self.assertEqual((decision, nid), (tact.LEVEL1, None))
        snap = rt.snapshot()
        self.assertEqual(snap["hint"]["text"], "남은 공간 9GB")
        self.assertEqual(snap["status_line"], "남은 공간 9GB")

    def test_mini_never_nudges(self):
        rt = pet.PetRuntime(edition="mini", **self.kw)
        self.assertEqual(rt.nudge("disk_low", "남은 공간 9GB", "용량 보기"), ("quiet", None))

    def test_broken_pipe_does_not_raise(self):
        rt = pet.PetRuntime(edition="pro", **self.kw)
        closed = io.StringIO()
        closed.close()
        rt.attach_host(closed)
        self.assertFalse(rt.send_host({"cmd": "toast"}))


if __name__ == "__main__":
    unittest.main()
