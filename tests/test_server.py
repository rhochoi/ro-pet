import json
import tempfile
import unittest
import urllib.error
import urllib.request

from ro_pet import server


class ServerTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tmp = tempfile.TemporaryDirectory()
        cls.pet = server.Pet(home=cls.tmp.name)
        cls.srv = server.start_server(cls.pet)
        cls.base = f"http://127.0.0.1:{cls.srv.server_address[1]}"

    @classmethod
    def tearDownClass(cls):
        cls.srv.shutdown()
        cls.srv.server_close()
        cls.tmp.cleanup()

    def call(self, path, body=None, token=True):
        headers = {"X-Ro-Token": self.pet.token} if token else {}
        data = json.dumps(body).encode() if body is not None else None
        req = urllib.request.Request(self.base + path, data=data, headers=headers)
        try:
            with urllib.request.urlopen(req) as r:
                return r.status, json.loads(r.read())
        except urllib.error.HTTPError as e:
            return e.code, json.loads(e.read())

    def test_page_is_english_and_carries_token(self):
        with urllib.request.urlopen(self.base + "/") as r:
            html = r.read().decode()
        self.assertIn(self.pet.token, html)
        self.assertNotRegex(html, "[가-힣]")

    def test_token_required(self):
        self.assertEqual(self.call("/api/state", token=False)[0], 403)
        self.assertEqual(self.call("/api/prefs", {"material": "glass"}, token=False)[0], 403)

    def test_prefs_roundtrip_and_validation(self):
        self.assertEqual(self.call("/api/prefs", {"material": "glass", "tint": "sky"})[1]["prefs"],
                         {"material": "glass", "tint": "sky"})
        self.assertEqual(self.call("/api/state")[1]["prefs"]["material"], "glass")
        self.assertFalse(self.call("/api/prefs", {"material": "wood"})[1]["ok"])

    def test_action(self):
        self.assertTrue(self.call("/api/action", {"action": "alert", "duration": 2})[1]["ok"])
        self.assertEqual(self.call("/api/state")[1]["action"], "alert")
        self.assertFalse(self.call("/api/action", {"action": "fly"})[1]["ok"])
        self.assertFalse(self.call("/api/action", {"action": "alert", "duration": 9999})[1]["ok"])

    def test_nothing_else_is_exposed(self):
        self.assertEqual(self.call("/api/organize/apply", {})[0], 404)


if __name__ == "__main__":
    unittest.main()


class PrebuiltHostTest(unittest.TestCase):
    def test_env_host_skips_swiftc(self):
        import os
        import stat
        from pathlib import Path

        from ro_pet.__main__ import ensure_mac_binary

        with tempfile.TemporaryDirectory() as d:
            fake = Path(d) / "host"
            fake.write_text("#!/bin/sh\n")
            fake.chmod(fake.stat().st_mode | stat.S_IXUSR)
            old = os.environ.get("RO_PET_HOST")
            os.environ["RO_PET_HOST"] = str(fake)
            try:
                self.assertEqual(ensure_mac_binary(), fake)
            finally:
                if old is None:
                    del os.environ["RO_PET_HOST"]
                else:
                    os.environ["RO_PET_HOST"] = old
