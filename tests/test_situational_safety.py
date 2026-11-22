"""Track C — Situational safety invariants:
1. Secret apps, fullscreen, camera/mic, and active typing emit 0 Level-2 notifications.
2. All situational triggers perform 0 unapproved file writes.
3. Every write proposal (installer, disk, archive, duplicate, organize) restores 100% of originals on 1-click undo.
"""

from __future__ import annotations

import os
from pathlib import Path
import tempfile
import time
import unittest
from unittest import mock

from ro import config, pet, scenarios, tact


def _snapshot(root: Path) -> dict[str, tuple[bytes, int]]:
    snap: dict[str, tuple[bytes, int]] = {}
    for p in sorted(root.rglob("*")):
        rel = p.relative_to(root)
        if any(part.startswith(".ro") for part in rel.parts):
            continue
        if p.is_file():
            st = p.stat()
            snap[str(rel)] = (p.read_bytes(), st.st_ino)
    return snap


def _touch(p: Path, payload: bytes, age_sec: float = 3600.0, now: float | None = None) -> Path:
    now = time.time() if now is None else now
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_bytes(payload)
    ts = now - age_sec
    os.utime(p, (ts, ts))
    return p


class SituationalSafetyTests(unittest.TestCase):
    ALL_TRIGGERS = (
        "dmg_installed",
        "disk_low",
        "old_version",
        "find_lost",
        "archive_unpacked",
        "duplicate_found",
        "download_burst",
        "context_switch",
    )

    def test_zero_level2_alerts_during_secret_apps_fullscreen_typing_or_av(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            ro_home = Path(td) / ".ro"
            log_dir = ro_home / "logs"
            ro_home.mkdir(parents=True, exist_ok=True)
            config.update(str(ro_home), pro_nudges=True)
            now = 1_750_000_000.0

            protected_sensor_states = [
                ("secret_1password", [{"type": "front", "app": "1Password 8", "t": now}]),
                ("secret_keychain", [{"type": "front", "app": "Keychain Access", "t": now}]),
                (
                    "secret_incognito",
                    [{"type": "front", "app": "Google Chrome", "window": "New Tab - 시크릿", "t": now}],
                ),
                (
                    "fullscreen",
                    [{"type": "front", "app": "Finder", "fullscreen": True, "t": now}],
                ),
                (
                    "typing_active",
                    [
                        {"type": "front", "app": "Notes", "fullscreen": False, "t": now},
                        {"type": "idle", "seconds": 0.4, "t": now},
                    ],
                ),
                (
                    "camera_or_mic_active",
                    [
                        {"type": "front", "app": "Zoom", "fullscreen": False, "t": now},
                        {"type": "capture", "active": True, "t": now},
                    ],
                ),
            ]

            level2_count = 0
            for state_name, events in protected_sensor_states:
                gate = tact.TactGate(home=str(ro_home), log_dir=str(log_dir), clock=lambda: now, daily_cap=20)
                for ev in events:
                    gate.on_sensor(ev)
                for trigger in self.ALL_TRIGGERS:
                    dec, reason = gate.decide(trigger, now=now)
                    if dec == tact.LEVEL2:
                        level2_count += 1
                    if state_name.startswith("secret_"):
                        self.assertEqual(
                            dec,
                            tact.DROP,
                            f"{state_name} must drop {trigger} (got {dec}, {reason})",
                        )
                    else:
                        self.assertEqual(
                            dec,
                            tact.LEVEL1,
                            f"{state_name} must downgrade {trigger} to level1 (got {dec}, {reason})",
                        )
            self.assertEqual(level2_count, 0, "Protected contexts must emit 0 Level-2 notifications")

    def test_zero_unapproved_file_writes_across_all_situational_triggers(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            home = Path(td).resolve() / "home"
            ro_home = home / ".ro"
            dl = home / "Downloads"
            docs = home / "Documents"
            apps = home / "Applications"
            for d in (ro_home, dl, docs, apps):
                d.mkdir(parents=True, exist_ok=True)

            now = time.time()
            # 1) Installed DMG + matching .app
            _touch(dl / "Linear-1.20.dmg", b"D" * 4096, age_sec=600, now=now)
            (apps / "Linear.app").mkdir()

            # 2) Unpacked archive + matching extracted folder
            _touch(dl / "BrandAssets.zip", b"Z" * 4096, age_sec=600, now=now)
            (dl / "BrandAssets").mkdir()
            _touch(dl / "BrandAssets" / "logo.svg", b"<svg/>", age_sec=600, now=now)

            # 3) Byte-identical duplicate download (non-financial filename)
            dup_payload = b"DESIGN-SPEC-V2-PAYLOAD" * 80
            _touch(dl / "DesignSpec.pdf", dup_payload, age_sec=700, now=now)
            _touch(dl / "DesignSpec (1).pdf", dup_payload, age_sec=600, now=now)

            # 4) Newer/older version pair
            _touch(dl / "Deck_v1.pdf", b"v1", age_sec=1200, now=now)
            _touch(dl / "Deck_v2.pdf", b"v2", age_sec=600, now=now)

            with mock.patch("pathlib.Path.home", return_value=home):
                config.update(str(ro_home), pro_nudges=True, roots=[str(dl), str(docs)])
                before = _snapshot(home)

                # Verify read-only detectors find the seeded items without touching disk
                self.assertEqual(len(scenarios.installed_installers(str(dl), app_dirs=(str(apps),), now=now)), 1)
                self.assertEqual(len(scenarios.unpacked_archives(str(dl), now=now)), 1)
                self.assertEqual(len(scenarios.duplicate_downloads(str(dl), now=now)), 1)

                rt = pet.PetRuntime(home=str(ro_home), log_dir=str(ro_home / "logs"), edition="pro")
                rt.pro.downloads = str(dl)
                rt.organize_root = str(dl)
                rt.organize_dest = str(docs / "Organized")
                rt.pro.free = lambda: 5 * 1024**3  # < 15GB disk_low threshold

                # Simulate download burst arrival + tick + AX + AI context switch + opening every preview card
                rt.tact.on_arrival(str(dl / "DesignSpec.pdf"), now=now - 30)
                rt.tact.on_arrival(str(dl / "DesignSpec (1).pdf"), now=now - 25)
                rt.pro.tick(now=now)
                rt.pro.on_ax({"document": str(dl / "Deck_v1.pdf")}, "Preview", now=now)
                rt.pro.on_front("Claude", now=now)
                rt.pro.on_front("Codex", now=now + 10)

                # Open preview cards without approving any write
                rt.pro._on_installer({"path": str(dl / "Linear-1.20.dmg")}, promoted=True)
                rt.pro._on_disk({"free": 5 * 1024**3}, promoted=True)
                rt.pro._on_archive({"path": str(dl / "BrandAssets.zip")}, promoted=True)
                rt.pro._on_duplicate({"items": scenarios.duplicate_downloads(str(dl), now=now)}, promoted=True)
                rt.pro._on_download_burst({"folder": str(dl)}, promoted=True)

                after = _snapshot(home)
                self.assertEqual(before, after, "Unapproved situational detections or previews modified user files!")

    def test_every_write_proposal_restores_100pct_on_one_click_undo(self) -> None:
        proposals = ("installer", "disk", "archive", "duplicate", "organize")
        for kind in proposals:
            with self.subTest(proposal=kind), tempfile.TemporaryDirectory() as td:
                home = Path(td).resolve() / "home"
                ro_home = home / ".ro"
                dl = home / "Downloads"
                docs = home / "Documents"
                apps = home / "Applications"
                projects = home / "Projects"
                for d in (ro_home, dl, docs, apps, projects):
                    d.mkdir(parents=True, exist_ok=True)

                now = time.time()
                dmg = _touch(dl / "Raycast.dmg", b"DMG-PAYLOAD" * 200, age_sec=900, now=now)
                (apps / "Raycast.app").mkdir()

                archive = _touch(dl / "IconsKit.zip", b"ZIP-DATA" * 300, age_sec=900, now=now)
                (dl / "IconsKit").mkdir()
                _touch(dl / "IconsKit" / "icon.png", b"PNG", age_sec=900, now=now)

                same_bytes = b"SPEC-DOC-CONTENT" * 120
                _touch(dl / "ProductSpec.pdf", same_bytes, age_sec=1000, now=now)
                dup = _touch(dl / "ProductSpec (1).pdf", same_bytes, age_sec=900, now=now)

                # Dead build for disk card (only seeded for 'disk' subtest to keep process RSS low)
                if kind == "disk":
                    proj = projects / "demo-app"
                    _touch(proj / "pyproject.toml", b"[project]\nname='demo'\n", age_sec=120 * 86400, now=now)
                    _touch(proj / ".venv" / "blob.bin", b"B" * (11 * 1024 * 1024), age_sec=120 * 86400, now=now)

                with mock.patch("pathlib.Path.home", return_value=home):
                    config.update(str(ro_home), pro_nudges=True, roots=[str(projects), str(dl), str(docs)])
                    rt = pet.PetRuntime(home=str(ro_home), log_dir=str(ro_home / "logs"), edition="pro")
                    rt.pro.downloads = str(dl)
                    rt.organize_root = str(dl)
                    rt.organize_dest = str(docs / "Organized")
                    if kind == "organize":
                        (docs / "Organized").mkdir(parents=True, exist_ok=True)

                    before = _snapshot(home)

                    if kind == "installer":
                        rt.pro._on_installer({"path": str(dmg)}, promoted=True)
                        cid = rt.pro.show
                    elif kind == "disk":
                        rt.pro._on_disk({"free": 5 * 1024**3}, promoted=True)
                        cid = rt.pro.show
                    elif kind == "archive":
                        rt.pro._on_archive({"path": str(archive)}, promoted=True)
                        cid = rt.pro.show
                    elif kind == "duplicate":
                        rt.pro._on_duplicate({"path": str(dup)}, promoted=True)
                        cid = rt.pro.show
                    else:
                        cid = rt.pro._build_organize_card(str(dl), str(docs / "Organized"))

                    self.assertIsNotNone(cid, f"{kind} must open a staging confirm card")
                    view = rt.pro.api({"op": "view", "id": cid})
                    self.assertTrue(view["ok"], f"{kind} card view failed: {view}")
                    picks = [it["id"] for it in view["card"]["items"]]
                    self.assertGreaterEqual(len(picks), 1)

                    # No filesystem mutation before explicit approval
                    self.assertEqual(before, _snapshot(home))

                    # Approve and apply
                    applied = rt.pro.api({"op": "apply", "id": cid, "picks": picks, "approve": True})
                    self.assertTrue(applied["ok"], f"{kind} apply failed: {applied}")
                    self.assertGreaterEqual(applied["moved"], 1)
                    self.assertTrue(applied["undo"])
                    self.assertNotEqual(before, _snapshot(home))

                    # 1-click Undo restores 100% of originals (every path, byte content, and inode)
                    undone = rt.pro.api({"op": "undo", "id": cid})
                    self.assertTrue(undone["ok"], f"{kind} undo failed: {undone}")
                    self.assertGreaterEqual(undone["restored"], 1)
                    after = _snapshot(home)
                    self.assertEqual(before, after, f"{kind} undo did not restore 100% of original files and inodes")


if __name__ == "__main__":
    unittest.main()
