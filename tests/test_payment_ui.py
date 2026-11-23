"""Tests for the in-app payment/upgrade modal, /api/license check flow, and commercial build readiness."""
import json
import os
import stat
import subprocess
import tempfile
import unittest
import urllib.request
from pathlib import Path
from unittest import mock

from ro import _ed25519, license, licensenet, ocr, pet

ROOT = Path(__file__).resolve().parent.parent
SEED = bytes(range(32))
PUB = _ed25519.public_key(SEED).hex()
NOW = 1_800_000_000


def make_key(exp=4_000_000_000):
    payload = {"v": 1, "kid": "t1", "id": "lic_pay_1", "plan": "pro", "iat": NOW, "exp": exp}
    return license.encode(payload, SEED)


class PaymentScreenMarkupAndWiringTest(unittest.TestCase):
    def test_in_app_payment_modal_present_in_mini_and_pro_html(self):
        for edition in ("mini", "pro"):
            html = pet.render_html("tok", {}, edition)
            for marker in (
                'id="proPlanBlock"',
                'id="proOpenBuyBtn"',
                'id="proOpenKeyBtn"',
                'id="proModal"',
                'id="proPlanYearly"',
                'id="proPlanMonthly"',
                'id="proCheckoutBtn"',
                'id="proRestartBtn"',
                "$24",
                "$3",
                "14-day refund",
            ):
                self.assertIn(marker, html, f"{edition}: missing {marker}")
            # Modal must NOT be hidden by pro-only so mini users can purchase Pro
            self.assertIn('<div id="proModal" class="palette" hidden>', html)

    def test_swift_host_wires_open_checkout_and_restart(self):
        swift = (ROOT / "ro/pet_mac.swift").read_text(encoding="utf-8")
        self.assertIn('type == "openCheckout"', swift)
        self.assertIn('type == "restartLicense"', swift)
        self.assertIn('url.scheme == "https"', swift)

    def test_license_api_check_activates_pro_and_requests_restart(self):
        with tempfile.TemporaryDirectory() as d, \
                mock.patch.object(license, "PUBLIC_KEYS", {"t1": PUB}), \
                mock.patch.dict(os.environ, {"RO_LICENSE_ISSUER": "https://issuer.test", "RO_EDITION_SOURCE": "license"}):
            rt = pet.PetRuntime(home=d, log_dir=d, map_path=str(Path(d) / "map.json"), edition="mini")
            buy = rt.license_api({"action": "buy", "plan": "yearly"})
            self.assertTrue(buy["ok"])
            self.assertTrue(buy["pending"])
            self.assertTrue(buy["url"].startswith("https://issuer.test/buy?plan=yearly&i="))

            st = rt.license_api({"action": "status"})
            self.assertTrue(st["pending"])
            self.assertEqual(st["state"], "none")

            key = make_key()
            with mock.patch.object(licensenet, "sync", side_effect=lambda home: (license.save(key, home), True)[1]):
                chk = rt.license_api({"action": "check"})
            self.assertTrue(chk["ok"])
            self.assertTrue(chk["activated"])
            self.assertTrue(chk["restart"])
            self.assertEqual(chk["state"], "valid")
            self.assertTrue(rt.restart_requested)

    def test_license_api_check_over_http_in_mini_edition(self):
        with tempfile.TemporaryDirectory() as d, mock.patch.object(licensenet, "ISSUER", ""):
            rt = pet.PetRuntime(home=d, log_dir=d, map_path=str(Path(d) / "map.json"), edition="mini")
            srv = pet.start_server(rt, "127.0.0.1", 0)
            try:
                url = f"http://127.0.0.1:{srv.server_address[1]}/api/license"
                req = urllib.request.Request(
                    url,
                    data=json.dumps({"action": "check"}).encode(),
                    headers={"Content-Type": "application/json", "X-Ro-Token": rt.token},
                )
                with urllib.request.urlopen(req, timeout=5) as r:
                    body = json.loads(r.read().decode())
                self.assertEqual(r.status, 200)
                self.assertTrue(body["ok"])
                self.assertFalse(body["activated"])
            finally:
                srv.shutdown()
                srv.server_close()


class CommercialBuildReadinessTest(unittest.TestCase):
    def test_ocr_uses_prebuilt_binary_from_env(self):
        with tempfile.TemporaryDirectory() as d:
            fake = Path(d) / "ro-ocr"
            fake.write_text("#!/bin/sh\nexit 0\n")
            fake.chmod(stat.S_IRWXU)
            with mock.patch.dict(os.environ, {"RO_OCR_BIN": str(fake)}):
                self.assertEqual(ocr._binary(d, 5), fake)

    def test_ocr_rejects_symlink_prebuilt_binary(self):
        with tempfile.TemporaryDirectory() as d:
            real = Path(d) / "real"
            real.write_text("#!/bin/sh\nexit 0\n")
            real.chmod(stat.S_IRWXU)
            link = Path(d) / "link"
            link.symlink_to(real)
            with mock.patch.dict(os.environ, {"RO_OCR_BIN": str(link)}), \
                    mock.patch("shutil.which", return_value=None):
                with self.assertRaises(ValueError):
                    ocr._binary(d, 5)

    def test_release_scripts_have_valid_shell_syntax(self):
        for rel in ("scripts/build-app.sh", "scripts/build-dmg.sh", "scripts/make-appcast.sh", "scripts/release-preflight.sh"):
            r = subprocess.run(["bash", "-n", str(ROOT / rel)], capture_output=True, text=True)
            self.assertEqual(r.returncode, 0, f"{rel}: {r.stderr}")


if __name__ == "__main__":
    unittest.main()
