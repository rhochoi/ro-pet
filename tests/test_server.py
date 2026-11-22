"""Compatibility entry point tests for `python3 -m ro_pet`."""
import unittest
from unittest import mock

import ro_pet
from ro_pet import __main__ as ro_pet_main


class RoPetCompatTest(unittest.TestCase):
    def test_package_exposes_ro_pet(self):
        self.assertTrue(hasattr(ro_pet.pet, "launch"))

    def test_main_forwards_flags_to_ro_pet_launch(self):
        with mock.patch.object(ro_pet_main.license_mod, "apply_edition_from_license") as apply_lic, \
                mock.patch.object(ro_pet_main.pet, "launch", return_value="http://127.0.0.1:8765/") as launch:
            rc = ro_pet_main.main(["--browser", "--no-wander", "--port", "9123"])
        self.assertEqual(rc, 0)
        apply_lic.assert_called_once()
        launch.assert_called_once_with(port=9123, mode="browser", wander=False, build_only=False)

    def test_build_only_returns_nonzero_when_missing(self):
        with mock.patch.object(ro_pet_main.pet, "launch", return_value=None):
            self.assertEqual(ro_pet_main.main(["--build-only"]), 1)
        with mock.patch.object(ro_pet_main.pet, "launch", return_value="/tmp/ro-pet-host"):
            self.assertEqual(ro_pet_main.main(["--build-only"]), 0)


if __name__ == "__main__":
    unittest.main()
