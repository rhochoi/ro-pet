import contextlib
import io
import json
import os
import stat
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from ro import _ed25519, harden, license

ROOT = Path(__file__).resolve().parent.parent
SEED = bytes(range(32))
OTHER = bytes(range(1, 33))
PUB = _ed25519.public_key(SEED).hex()
NOW = 1_800_000_000


def make(seed=SEED, **over):
    payload = {"v": 1, "kid": "t1", "id": "lic_1", "plan": "pro", "iat": NOW, "exp": NOW + 86400}
    payload.update(over)
    return license.encode(payload, seed)


class Ed25519Test(unittest.TestCase):
    def test_rfc8032_vectors(self):
        # RFC 8032 7.1 TEST 1·2
        for seed, pub, msg, sig in [
            ("9d61b19deffd5a60ba844af492ec2cc44449c5697b326919703bac031cae7f60",
             "d75a980182b10ab7d54bfed3c964073a0ee172f3daa62325af021a68f707511a", "",
             "e5564300c360ac729086e2cc806e828a84877f1eb8e5d974d873e065224901555fb8821590a33bacc61e39701cf9b46bd25bf5f0595bbe24655141438e7a100b"),
            ("4ccd089b28ff96da9db6c346ec114e0f5b8a319f35aba624da8cf6ed4fb8a6fb",
             "3d4017c3e843895a92b70aa74d1b7ebc9c982ccf2ec4968cc0cd55f12af4660c", "72",
             "92a009a9f0d4cab8720e820b5f642540a2b27b5416503f8fb3762223ebdb69da085ac1e43e15996e458f3613d0f11d8c387b2eaeb4302aeeb00d291612bb0c00"),
        ]:
            s, m = bytes.fromhex(seed), bytes.fromhex(msg)
            self.assertEqual(_ed25519.public_key(s).hex(), pub)
            self.assertEqual(_ed25519.sign(s, m).hex(), sig)
            self.assertTrue(_ed25519.verify(bytes.fromhex(pub), m, bytes.fromhex(sig)))
            self.assertFalse(_ed25519.verify(bytes.fromhex(pub), m + b"x", bytes.fromhex(sig)))

    def test_malformed_inputs_are_false_not_errors(self):
        for pub, sig in [(b"", b""), (b"\x00" * 32, b"\x00" * 64), (b"\xff" * 32, b"\xff" * 64), ("x", b"")]:
            self.assertFalse(_ed25519.verify(pub, b"m", sig))


class LicenseParseTest(unittest.TestCase):
    def setUp(self):
        p = mock.patch.object(license, "PUBLIC_KEYS", {"t1": PUB})
        p.start()
        self.addCleanup(p.stop)

    def test_valid_key(self):
        self.assertEqual(license.parse(make(), now=NOW)["id"], "lic_1")
        self.assertEqual(license.parse("  " + make() + "\n", now=NOW)["plan"], "pro")

    def test_rejections(self):
        good = make()
        head, body, sig = good.split(".")
        forged = license._b64e(b'{"v":1,"kid":"t1","plan":"pro","exp":9999999999}')
        cases = {
            "expired": (make(exp=NOW - 1), "만료"),
            "expires now": (make(exp=NOW), "만료"),
            "other signer": (make(seed=OTHER), "서명"),
            "unknown kid": (make(kid="zz"), "알지 못하는"),
            "tampered body": (f"{head}.{forged}.{sig}", "서명"),
            "wrong plan": (make(plan="team"), "내용"),
            "bool exp": (make(exp=True), "내용"),
            "string exp": (make(exp="9999999999"), "내용"),
            "version": (make(v=2), "버전"),
            "prefix": ("RO2." + body + "." + sig, "아닙니다"),
            "parts": ("RO1." + body, "아닙니다"),
            "empty": ("", "비어"),
            "garbage b64": ("RO1.!!!.???", "형식"),
            "not json": (f"RO1.{license._b64e(b'nope')}.{sig}", "형식"),
            "too long": ("RO1." + "a" * 3000 + ".b", "깁니다"),
        }
        for name, (key, word) in cases.items():
            with self.subTest(name), self.assertRaises(license.LicenseError) as ctx:
                license.parse(key, now=NOW)
            self.assertIn(word, str(ctx.exception), name)

    def test_no_public_keys_means_nothing_validates(self):
        with self.assertRaises(license.LicenseError):
            license.parse(make(), now=NOW, keys={})


class LicenseStoreTest(unittest.TestCase):
    def setUp(self):
        p = mock.patch.object(license, "PUBLIC_KEYS", {"t1": PUB})
        p.start()
        self.addCleanup(p.stop)
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.home = tmp.name

    def test_save_status_remove(self):
        self.assertEqual(license.status(self.home, NOW)["state"], "none")
        self.assertEqual(license.edition(self.home, NOW), "mini")
        license.save(make(), self.home, now=NOW)
        path = Path(self.home) / "license"
        self.assertEqual(stat.S_IMODE(path.stat().st_mode), 0o600)
        self.assertEqual(license.status(self.home, NOW)["state"], "valid")
        self.assertEqual(license.edition(self.home, NOW), "pro")
        self.assertEqual(license.edition(self.home, NOW + 86400), "mini")  # 만료되면 mini
        self.assertTrue(license.remove(self.home))
        self.assertFalse(license.remove(self.home))
        self.assertEqual(license.edition(self.home, NOW), "mini")

    def test_invalid_save_keeps_existing_key(self):
        license.save(make(), self.home, now=NOW)
        with self.assertRaises(license.LicenseError):
            license.save(make(seed=OTHER), self.home, now=NOW)
        self.assertEqual(license.edition(self.home, NOW), "pro")

    def test_corrupt_file_is_mini(self):
        (Path(self.home) / "license").write_bytes(b"\xff\xfe garbage")
        self.assertEqual(license.edition(self.home, NOW), "mini")
        self.assertEqual(license.status(self.home, NOW)["state"], "none")


class EditionSourceTest(unittest.TestCase):
    def test_env_pro_is_overridden_without_key(self):
        with mock.patch.dict(os.environ, {"RO_EDITION": "pro", "RO_EDITION_SOURCE": "license"}), \
                mock.patch.object(license, "edition", return_value="mini"):
            license.apply_edition_from_license()
            self.assertEqual(os.environ["RO_EDITION"], "mini")

    def test_valid_key_turns_pro(self):
        with mock.patch.dict(os.environ, {"RO_EDITION": "mini", "RO_EDITION_SOURCE": "license"}), \
                mock.patch.object(license, "edition", return_value="pro"):
            license.apply_edition_from_license()
            self.assertEqual(os.environ["RO_EDITION"], "pro")

    def test_untouched_outside_app(self):
        with mock.patch.dict(os.environ, {"RO_EDITION": "pro"}):
            os.environ.pop("RO_EDITION_SOURCE", None)
            license.apply_edition_from_license()
            self.assertEqual(os.environ["RO_EDITION"], "pro")

    def test_entrypoint_applies_before_cli(self):
        with tempfile.TemporaryDirectory() as home:
            env = {**os.environ, "HOME": home, "RO_EDITION": "pro", "RO_EDITION_SOURCE": "license"}
            out = subprocess.run([sys.executable, "-c",
                                  "import runpy,sys,os; sys.argv=['ro','license','status']\n"
                                  "try: runpy.run_module('ro', run_name='__main__')\n"
                                  "except SystemExit: pass\n"
                                  "print(os.environ['RO_EDITION'])"],
                                 cwd=ROOT, env=env, capture_output=True, text=True, timeout=60)
            self.assertEqual(out.stdout.strip().splitlines()[-1], "mini", out.stderr)

    def test_launcher_uses_license_source(self):
        text = (ROOT / "scripts/build-app.sh").read_text()
        self.assertIn("export RO_EDITION=mini", text)
        self.assertIn("export RO_EDITION_SOURCE=license", text)

    def test_license_module_has_no_network(self):
        self.assertFalse([o for o in harden.network_offenders() if "license" in o or "_ed25519" in o])


class LicenseToolTest(unittest.TestCase):
    def run_tool(self, *args):
        return subprocess.run([sys.executable, str(ROOT / "scripts/license-tool.py"), *args],
                              capture_output=True, text=True, timeout=60)

    def test_keygen_issue_roundtrip_and_refusals(self):
        with tempfile.TemporaryDirectory() as d:
            seed = Path(d) / "seed"
            r = self.run_tool("keygen", "--out", str(seed))
            self.assertEqual(r.returncode, 0, r.stderr)
            pub = r.stdout.strip()
            self.assertEqual(len(pub), 64)
            self.assertEqual(stat.S_IMODE(seed.stat().st_mode), 0o600)
            self.assertNotIn(seed.read_text().strip(), r.stdout + r.stderr)  # 개인 시드는 출력하지 않는다
            self.assertNotEqual(self.run_tool("keygen", "--out", str(seed)).returncode, 0)  # 덮어쓰기 거부
            r = self.run_tool("issue", "--secret", str(seed), "--kid", "k1", "--id", "x", "--days", "30")
            self.assertEqual(r.returncode, 0, r.stderr)
            self.assertEqual(license.parse(r.stdout.strip(), keys={"k1": pub})["id"], "x")
        r = self.run_tool("keygen", "--out", str(ROOT / "seed-should-not-exist"))
        self.assertNotEqual(r.returncode, 0)
        self.assertFalse((ROOT / "seed-should-not-exist").exists())


    def test_issue_bad_period_is_refused_without_traceback(self):
        """RO-AUD-109: --days 0·음수·없는 날짜·지난 날짜는 한 줄 안내로 거부하고 키를 내지 않는다."""
        with tempfile.TemporaryDirectory() as d:
            seed = Path(d) / "seed"
            self.assertEqual(self.run_tool("keygen", "--out", str(seed)).returncode, 0)
            for args in (["--days", "0"], ["--days", "-3"], ["--until", "2026-13-45"], ["--until", "2000-01-01"]):
                r = self.run_tool("issue", "--secret", str(seed), "--kid", "k1", "--id", "x", *args)
                self.assertNotEqual(r.returncode, 0, args)
                self.assertNotIn("Traceback", r.stderr, args)
                self.assertTrue(r.stderr.strip(), args)
                self.assertNotIn("RO1.", r.stdout, args)

class NoUserKeyUiTest(unittest.TestCase):
    def test_no_user_facing_key_commands(self):
        from ro import cli
        self.assertFalse(hasattr(license, "main"))
        r = subprocess.run([sys.executable, "-m", "ro", "license", "set", "x"], capture_output=True, text=True, cwd=ROOT)
        self.assertNotEqual(r.returncode, 0)
        swift = (ROOT / "ro/pet_mac.swift").read_text(encoding="utf-8")
        for gone in ("openLicense", "showLicenseDialog", "Save key", "Paste the key", "RO1.…"):
            self.assertNotIn(gone, swift)
        self.assertNotIn("license", cli.build_parser().format_help() if hasattr(cli, "build_parser") else "")


class PetLicenseApiTest(unittest.TestCase):
    """메뉴 막대 라이선스 창이 쓰는 /api/license: mini에서도 열려 있고, 키를 응답에 싣지 않는다."""

    def setUp(self):
        import json
        import urllib.error
        import urllib.request
        from ro import pet
        self.json, self.urlerror, self.urlreq, self.pet = json, urllib.error, urllib.request, pet
        p = mock.patch.object(license, "PUBLIC_KEYS", {"t1": PUB})
        p.start()
        self.addCleanup(p.stop)
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.home = tmp.name
        self.rt = pet.PetRuntime(home=self.home, log_dir=self.home, map_path=str(Path(self.home) / "map.json"),
                                 edition="mini")
        self.server = pet.start_server(self.rt)
        self.addCleanup(self.server.server_close)
        self.addCleanup(self.server.shutdown)

    def post(self, path, body):
        req = self.urlreq.Request(f"http://127.0.0.1:{self.server.server_address[1]}{path}",
                                  data=self.json.dumps(body).encode(), method="POST",
                                  headers={"Content-Type": "application/json", "X-Ro-Token": self.rt.token})
        try:
            with self.urlreq.urlopen(req, timeout=10) as r:
                return r.status, r.read().decode()
        except self.urlerror.HTTPError as e:
            return e.code, e.read().decode()

    def test_status_only_and_key_actions_are_gone(self):
        code, raw = self.post("/api/license", {"action": "status"})
        self.assertEqual((code, self.json.loads(raw)["state"]), (200, "none"))
        for act in ("set", "remove", "wipe"):
            self.assertEqual(self.post("/api/license", {"action": act, "key": make()})[0], 400)
        self.assertFalse((Path(self.home) / "license").exists())

    def test_mini_still_locks_pro_routes(self):
        self.assertEqual(self.post("/api/recall", {"question": "x"})[0], 403)

    def test_restart_reexecs_same_command(self):
        with mock.patch.object(self.pet.os, "execv") as ex, mock.patch.object(sys, "argv", ["/x/ro/__main__.py", "pet"]):
            self.pet._restart_self()
        ex.assert_called_once_with(sys.executable, [sys.executable, "-m", "ro", "pet"])

    def test_host_and_page_wiring(self):
        swift = (ROOT / "ro/pet_mac.swift").read_text(encoding="utf-8")
        js = (ROOT / "ro/pet_ui/pet.js").read_text(encoding="utf-8")
        self.assertIn("window.licenseFromHost(body)", swift)
        self.assertIn('apiPost("/api/license"', js)
        src = (ROOT / "ro/pet.py").read_text(encoding="utf-8")
        self.assertIn("restart = (child_proc.wait() == RESTART_EXIT and runtime.restart_requested) or runtime.force_restart", src)


class ProductionKeyTest(unittest.TestCase):
    def test_production_keys_are_valid_points_and_match_the_issuer(self):
        import re
        self.assertTrue(license.PUBLIC_KEYS)  # 비면 아무 키도 통과하지 못한다
        for kid, pub in license.PUBLIC_KEYS.items():
            raw = bytes.fromhex(pub)
            self.assertEqual(len(raw), 32, kid)
            self.assertIsNotNone(_ed25519._decompress(raw), kid)  # 곡선 위의 점(오타가 아님)
        kid = re.search(r'^LICENSE_KID = "([^"]*)"', (ROOT / "issuer/wrangler.toml").read_text(), re.M).group(1)
        self.assertIn(kid, license.PUBLIC_KEYS)  # 발급기가 서명하는 kid를 앱이 안다

    def test_unknown_signer_is_still_rejected(self):
        with self.assertRaises(license.LicenseError):
            license.parse(make(kid="ro1"), now=NOW)  # 시험 시드로 서명한 ro1 키는 운영 공개 키와 맞지 않는다


class LicenseNetTest(unittest.TestCase):
    """자동 활성화의 앱 쪽(ro/licensenet.py): 설치 토큰 하나만 보내고, 받은 키는 이 Mac에서 다시 검사한다."""

    def setUp(self):
        from ro import licensenet
        self.net = licensenet
        for p in (mock.patch.object(license, "PUBLIC_KEYS", {"t1": PUB}),
                  mock.patch.dict(os.environ, {"RO_LICENSE_ISSUER": "https://issuer.test/"})):
            p.start()
            self.addCleanup(p.stop)
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.home = tmp.name

    def test_shipped_issuer_is_set(self):
        # 발급기 주소가 비면 'Get pro…'가 결제창을 못 연다(0.5.2 사고). 소스에는 운영 주소가 들어 있어야 한다.
        self.assertRegex(self.net.ISSUER, r"^https://[^\s\"']+$")

    def test_token_is_private_random_and_only_its_hash_goes_in_the_buy_url(self):
        import hashlib
        t = self.net.token(self.home)
        self.assertEqual((len(t), self.net.token(self.home)), (43, t))   # 한 번 만들면 그대로
        self.assertEqual(stat.S_IMODE((Path(self.home) / "install-token").stat().st_mode), 0o600)
        url = self.net.buy_url("yearly", self.home, now=NOW)
        self.assertEqual(url, f"https://issuer.test/buy?plan=yearly&i={hashlib.sha256(t.encode()).hexdigest()}")
        self.assertNotIn(t, url)
        self.assertTrue(self.net.pending(self.home, NOW + 60))
        self.assertFalse(self.net.pending(self.home, NOW + self.net.PENDING_SECONDS + 1))
        with self.assertRaises(ValueError):
            self.net.buy_url("lifetime", self.home)

    def test_contact_only_while_pending_or_once_a_day_on_pro_and_never_when_off(self):
        self.assertFalse(self.net.due(self.home, NOW, "mini"))             # 사지도 않았으면 연락 없음
        self.assertTrue(self.net.due(self.home, NOW, "pro"))               # pro면 하루 한 번
        self.net.sync(self.home, NOW, fetch=lambda h: None)
        self.assertFalse(self.net.due(self.home, NOW + 3600, "pro"))
        self.assertTrue(self.net.due(self.home, NOW + 86400, "pro"))
        self.net.buy_url("monthly", self.home, now=NOW + 10)
        self.assertTrue(self.net.due(self.home, NOW + 20, "mini"))         # 구매 대기: 15초마다
        self.assertFalse(self.net.due(self.home, NOW + 11, "mini"))
        self.net.auto(False, self.home)
        self.assertFalse(self.net.due(self.home, NOW + 86400 * 2, "pro"))  # 끄면 연락하지 않는다
        self.net.auto(True, self.home)
        with mock.patch.dict(os.environ, {"RO_LICENSE_ISSUER": ""}), mock.patch.object(self.net, "ISSUER", ""):
            self.assertFalse(self.net.active(self.home))                   # 발급기 주소가 없으면 꺼진 것과 같다
            self.assertIsNone(self.net.buy_url("yearly", self.home))

    def test_fetch_posts_only_the_token_and_sync_keeps_the_later_valid_key(self):
        sent = []
        key = make(exp=NOW + 400 * 86400)
        def post(url, body, timeout):
            sent.append((url, body))
            return 200, json.dumps({"key": key}).encode()
        self.assertEqual(self.net.fetch(self.home, post=post), key)
        self.assertEqual(sent, [("https://issuer.test/license", {"install": self.net.token(self.home)})])
        self.assertIsNone(self.net.fetch(self.home, post=lambda u, b, t: (404, b"{}")))
        self.assertIsNone(self.net.fetch(self.home, post=lambda u, b, t: (None, b"")))
        self.net.buy_url("yearly", self.home, now=NOW)
        self.assertTrue(self.net.sync(self.home, NOW, fetch=lambda h: key))
        self.assertEqual(license.edition(self.home, NOW), "pro")
        self.assertFalse(self.net.pending(self.home, NOW))                  # 받았으면 구매 대기 끝
        self.assertFalse(self.net.sync(self.home, NOW, fetch=lambda h: make(exp=NOW + 86400)))  # 더 일찍 끝나는 키는 무시
        self.assertFalse(self.net.sync(self.home, NOW, fetch=lambda h: make(seed=OTHER, exp=NOW + 900 * 86400)))  # 위조는 무시
        self.assertEqual(license.parse(license.load(self.home), now=NOW)["exp"], NOW + 400 * 86400)

    def test_pet_restarts_itself_when_a_fetched_key_turns_mini_into_pro(self):
        from ro import pet
        rt = pet.PetRuntime(home=self.home, log_dir=self.home, map_path=str(Path(self.home) / "map.json"), edition="mini")
        called = []
        rt.on_force_restart = lambda: called.append(1)
        key = make(exp=NOW + 400 * 86400)
        self.assertFalse(rt.license_tick(now=NOW, fetch=lambda h: key))     # 구매 대기가 아니면 연락도 없다
        with mock.patch("time.time", return_value=NOW):
            res = rt.license_api({"action": "buy", "plan": "yearly"})
        self.assertTrue(res["ok"] and res["url"].startswith("https://issuer.test/buy?plan=yearly&i="))
        with mock.patch.dict(os.environ, {"RO_EDITION_SOURCE": "license"}), mock.patch("time.time", return_value=NOW + 30):
            self.assertTrue(rt.license_tick(now=NOW + 30, fetch=lambda h: key))
        self.assertEqual((rt.force_restart, called), (True, [1]))
        self.assertFalse(rt.license_api({"action": "auto", "on": False})["auto"])
        self.assertEqual(rt.license_api({"action": "buy", "plan": "x"})["ok"], False)

    def test_network_check_allows_only_the_scoped_license_file(self):
        self.assertEqual(harden.network_offenders(), [])
        self.assertEqual(harden.license_net_scoped(), [])
        with tempfile.TemporaryDirectory() as d:
            bad = Path(d) / "licensenet.py"
            bad.write_text("import socket\nimport urllib.request\nA = 'https://a.example'\nB = 'https://b.example'\n"
                           "def send(t, e):\n    return urllib.request.urlopen('x', data={'install': t, 'email': e})\n")
            reasons = " ".join(harden.license_net_scoped(bad))
            for word in ("원격 주소 2개", "import socket", "다른 값", "_post"):
                self.assertIn(word, reasons)
            sub = Path(d) / "sub"
            sub.mkdir()
            (sub / "licensenet.py").write_text("import socket\n")   # 허용은 ro 바로 아래 그 파일 하나뿐
            self.assertTrue(harden.network_offenders(d))

    def test_get_pro_menu_is_wired(self):
        swift = (ROOT / "ro/pet_mac.swift").read_text(encoding="utf-8")
        self.assertIn("#selector(openGetPro)", swift)
        self.assertIn('licenseCall(["action": "buy", "plan": plan])', swift)
        self.assertIn('url.scheme == "https"', swift)
        self.assertIn('L("Turn pro on automatically after I pay")', swift)          # 끄는 자리가 화면에 있다
        self.assertIn('licenseCall(["action": "auto", "on": box.state == .on])', swift)


if __name__ == "__main__":
    unittest.main()
