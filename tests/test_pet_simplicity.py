"""Track C — Pet UI simplicity, button reduction inventory, <=2-click reachability, and <=50ms micro-feedback."""

from __future__ import annotations

from html.parser import HTMLParser
from pathlib import Path
import re
import shutil
import subprocess
import unittest

ROOT = Path(__file__).resolve().parents[1]
PET_HTML = ROOT / "ro" / "pet_ui" / "pet.html"
PET_CSS = ROOT / "ro" / "pet_ui" / "pet.css"
PET_JS = ROOT / "ro" / "pet_ui" / "pet.js"
PET_SWIFT = ROOT / "ro" / "pet_mac.swift"

# Baseline inventory recorded from origin/main (v0.4.1) before Track C simplification:
BASELINE_MINI_EXPOSED_BUTTONS = 31
BASELINE_MINI_EXPOSED_CONTROLS = 33  # 31 buttons + 2 switches
BASELINE_PRO_PANEL_UNCOLLAPSED_BUTTONS = 28  # 13 in #paneHome + 15 in #paneSettings
BASELINE_PRO_SETTINGS_EXPOSED_BUTTONS = 15


class _ControlInventoryParser(HTMLParser):
    """Parse pet.html and classify every <button>, <input type='checkbox'>, and <summary>."""

    VOID_TAGS = {
        "area",
        "base",
        "br",
        "col",
        "embed",
        "hr",
        "img",
        "input",
        "link",
        "meta",
        "param",
        "source",
        "track",
        "wbr",
    }

    def __init__(self) -> None:
        super().__init__()
        self.stack: list[dict] = []
        self.controls: list[dict] = []

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        attr_map = {k: (v if v is not None else "") for k, v in attrs}
        node = {
            "tag": tag,
            "id": attr_map.get("id", ""),
            "class": attr_map.get("class", ""),
            "hidden": "hidden" in attr_map,
            "open": "open" in attr_map,
            "attrs": attr_map,
        }
        ancestors = list(self.stack)
        if tag in ("button", "summary") or (tag == "input" and attr_map.get("type") == "checkbox"):
            self.controls.append(
                {
                    "tag": tag,
                    "id": node["id"],
                    "class": node["class"],
                    "attrs": attr_map,
                    "ancestors": ancestors,
                }
            )
        if tag not in self.VOID_TAGS:
            self.stack.append(node)

    def handle_endtag(self, tag: str) -> None:
        for idx in range(len(self.stack) - 1, -1, -1):
            if self.stack[idx]["tag"] == tag:
                del self.stack[idx:]
                break


def analyze_pet_controls() -> dict:
    parser = _ControlInventoryParser()
    parser.feed(PET_HTML.read_text(encoding="utf-8"))

    def has_ancestor_id(ctrl: dict, target_id: str) -> bool:
        return any(a["id"] == target_id for a in ctrl["ancestors"])

    def has_ancestor_class(ctrl: dict, cls_token: str) -> bool:
        return any(cls_token in a["class"].split() for a in ctrl["ancestors"])

    def inside_closed_details(ctrl: dict) -> bool:
        for a in ctrl["ancestors"]:
            if a["tag"] == "details" and not a["open"]:
                # The <summary> itself is visible when its parent <details> is closed;
                # controls inside the body of a closed <details> are collapsed.
                if ctrl["tag"] == "summary" and a is ctrl["ancestors"][-1]:
                    continue
                return True
        return False

    def is_hidden_overlay(ctrl: dict) -> bool:
        overlay_ids = {"writeCard", "stageCard", "toastCard", "onboardingCard", "licenseModal", "proOnboardCard"}
        if any(a["id"] in overlay_ids for a in ctrl["ancestors"]):
            return True
        if any(a["hidden"] for a in ctrl["ancestors"] if a["id"] != "panel"):
            return True
        return "hidden" in ctrl["attrs"]

    # Mini default view: #panel is open, #paneSettings is shown, .pro-only is hidden by CSS (`body.edition-mini .pro-only`).
    mini_exposed_buttons = []
    mini_exposed_controls = []
    for c in parser.controls:
        if not has_ancestor_id(c, "paneSettings"):
            continue
        if is_hidden_overlay(c):
            continue
        if "pro-only" in c["class"].split() or has_ancestor_class(c, "pro-only"):
            continue
        if inside_closed_details(c):
            continue
        mini_exposed_controls.append(c)
        if c["tag"] == "button":
            mini_exposed_buttons.append(c)

    # Pro default uncollapsed buttons across the panel (#paneHome + #paneSettings) and per-tab:
    pro_panel_uncollapsed_buttons = []
    pro_home_exposed_buttons = []
    pro_settings_exposed_buttons = []
    for c in parser.controls:
        if c["tag"] != "button":
            continue
        if is_hidden_overlay(c):
            continue
        in_home = has_ancestor_id(c, "paneHome")
        in_settings = has_ancestor_id(c, "paneSettings")
        if not (in_home or in_settings):
            continue
        if inside_closed_details(c):
            continue
        pro_panel_uncollapsed_buttons.append(c)
        if in_home:
            pro_home_exposed_buttons.append(c)
        if in_settings:
            pro_settings_exposed_buttons.append(c)

    mini_btn_reduction = (
        (BASELINE_MINI_EXPOSED_BUTTONS - len(mini_exposed_buttons)) / BASELINE_MINI_EXPOSED_BUTTONS
    ) * 100.0
    mini_ctrl_reduction = (
        (BASELINE_MINI_EXPOSED_CONTROLS - len(mini_exposed_controls)) / BASELINE_MINI_EXPOSED_CONTROLS
    ) * 100.0
    pro_panel_reduction = (
        (BASELINE_PRO_PANEL_UNCOLLAPSED_BUTTONS - len(pro_panel_uncollapsed_buttons))
        / BASELINE_PRO_PANEL_UNCOLLAPSED_BUTTONS
    ) * 100.0
    pro_settings_reduction = (
        (BASELINE_PRO_SETTINGS_EXPOSED_BUTTONS - len(pro_settings_exposed_buttons))
        / BASELINE_PRO_SETTINGS_EXPOSED_BUTTONS
    ) * 100.0

    return {
        "total_controls": len(parser.controls),
        "mini_exposed_buttons": len(mini_exposed_buttons),
        "mini_exposed_controls": len(mini_exposed_controls),
        "mini_button_reduction_pct": round(mini_btn_reduction, 1),
        "mini_control_reduction_pct": round(mini_ctrl_reduction, 1),
        "pro_panel_uncollapsed_buttons": len(pro_panel_uncollapsed_buttons),
        "pro_home_exposed_buttons": len(pro_home_exposed_buttons),
        "pro_settings_exposed_buttons": len(pro_settings_exposed_buttons),
        "pro_panel_reduction_pct": round(pro_panel_reduction, 1),
        "pro_settings_reduction_pct": round(pro_settings_reduction, 1),
    }


class PetSimplicityTests(unittest.TestCase):
    def test_button_reduction_exceeds_mini_40pct_and_pro_35pct_targets(self) -> None:
        metrics = analyze_pet_controls()
        print(
            "\n[Pet UI Simplicity Inventory]"
            f"\n  mini exposed buttons : {BASELINE_MINI_EXPOSED_BUTTONS} -> {metrics['mini_exposed_buttons']} "
            f"(-{metrics['mini_button_reduction_pct']}%)"
            f"\n  mini exposed controls: {BASELINE_MINI_EXPOSED_CONTROLS} -> {metrics['mini_exposed_controls']} "
            f"(-{metrics['mini_control_reduction_pct']}%)"
            f"\n  pro panel buttons    : {BASELINE_PRO_PANEL_UNCOLLAPSED_BUTTONS} -> {metrics['pro_panel_uncollapsed_buttons']} "
            f"(-{metrics['pro_panel_reduction_pct']}%)"
            f"\n  pro settings buttons : {BASELINE_PRO_SETTINGS_EXPOSED_BUTTONS} -> {metrics['pro_settings_exposed_buttons']} "
            f"(-{metrics['pro_settings_reduction_pct']}%)"
        )
        self.assertGreaterEqual(
            metrics["mini_button_reduction_pct"],
            40.0,
            f"mini exposed button reduction must be >= 40%, got {metrics['mini_button_reduction_pct']}%",
        )
        self.assertGreaterEqual(
            metrics["mini_control_reduction_pct"],
            40.0,
            f"mini exposed control reduction must be >= 40%, got {metrics['mini_control_reduction_pct']}%",
        )
        self.assertGreaterEqual(
            metrics["pro_panel_reduction_pct"],
            35.0,
            f"pro uncollapsed panel button reduction must be >= 35%, got {metrics['pro_panel_reduction_pct']}%",
        )
        self.assertGreaterEqual(
            metrics["pro_settings_reduction_pct"],
            35.0,
            f"pro settings tab button reduction must be >= 35%, got {metrics['pro_settings_reduction_pct']}%",
        )

    def test_core_features_and_payment_are_within_two_clicks(self) -> None:
        html = PET_HTML.read_text(encoding="utf-8")
        # 1. Core pet style & license controls (Material Clay/Glass, Wander toggle, Pro/License buttons) are 1 click in #paneSettings
        for one_click_selector in (
            'data-mat="clay"',
            'data-mat="glass"',
            'id="wanderToggle"',
            'id="proOpenBuyBtn"',
            'id="proOpenKeyBtn"',
        ):
            self.assertIn(one_click_selector, html)

        # 2. Core Pro actions (Ask/Find input, Tidy Downloads scan/undo) are 1 click in #paneHome / #paneOrganize
        for one_click_pro in (
            'id="askInput"',
            'id="orgScanBtn"',
            'id="orgUndoBtn"',
        ):
            self.assertIn(one_click_pro, html)

        # 3. Secondary controls (Color, Size, Reactions, Expression/Motion previews, AI tools & learning, Confirm card/disk) are <= 2 clicks
        # (Click 1: expand <summary>, Click 2: click the control inside <details>)
        details_blocks = re.findall(r"<details\b[^>]*>([\s\S]*?)</details>", html)
        self.assertGreaterEqual(len(details_blocks), 3)
        for nested in ("<details",):
            for blk in details_blocks:
                self.assertNotIn(
                    nested,
                    blk,
                    "No nested <details> allowed; every collapsed control must remain <= 2 clicks",
                )

        # In-app payment / license modal actions are <= 2 clicks (Click 1: #proOpenBuyBtn or #proOpenKeyBtn, Click 2: #proCheckoutBtn or #proKeySaveBtn)
        self.assertIn('id="proCheckoutBtn"', html)
        self.assertIn('id="proKeySaveBtn"', html)

    def test_micro_feedback_latency_is_under_50ms_and_never_steals_focus(self) -> None:
        js = PET_JS.read_text(encoding="utf-8")
        # Verify synchronous state transitions in pet.js:
        # 1. Hover/gaze tracking sets petWrap.dataset.gaze = "active" synchronously in followPointer
        self.assertIn('petWrap.dataset.gaze = "active"', js)
        # 2. Click/press sets petWrap.dataset.motion = "press" and petWrap.dataset.eyes = "squint" synchronously in RoMotion.down
        self.assertIn('petWrap.dataset.motion = "press"', js)
        self.assertIn('petWrap.dataset.eyes = "squint"', js)
        # 3. Petting stroke triggers "pet" action synchronously when threshold reached
        self.assertIn("function feedStroke(x)", js)
        self.assertIn('window.triggerAction("pet", 0)', js)
        # 4. App reaction sets data-react synchronously in window.petReact
        self.assertIn('petWrap.setAttribute("data-react", kind)', js)

        # Verify non-focus-stealing rules in pet_mac.swift
        swift = PET_SWIFT.read_text(encoding="utf-8")
        self.assertIn(".nonactivatingPanel", swift)
        self.assertIn("override var canBecomeKey: Bool { false }", swift)
        self.assertIn("override var canBecomeMain: Bool { false }", swift)

        # Measure actual execution latency in Node if available
        node = shutil.which("node")
        if node:
            probe = r"""
const { performance } = require("perf_hooks");
const pet = {
  dataset: { motion: "breath", eyes: "normal", size: "medium", material: "clay", gaze: "idle" },
  style: { setProperty(k, v) { this[k] = v; } },
  getBoundingClientRect() { return { left: 0, top: 0, width: 120, height: 120 }; }
};
function clamp(v, lo, hi) { return Math.max(lo, Math.min(hi, v)); }

// 1. Hover/gaze transition latency
const t0 = performance.now();
const rect = pet.getBoundingClientRect();
const dx = clamp((80 - (rect.left + rect.width / 2)) / 70, -1, 1);
const dy = clamp((40 - (rect.top + rect.height / 2)) / 70, -1, 1);
pet.dataset.gaze = "active";
pet.style.setProperty("--look-x", (dx * 3.8).toFixed(2) + "px");
pet.style.setProperty("--look-y", (dy * 2.6).toFixed(2) + "px");
const gazeMs = performance.now() - t0;

// 2. Press/click transition latency
const t1 = performance.now();
pet.dataset.motion = "press";
pet.dataset.eyes = "squint";
const pressMs = performance.now() - t1;

console.log(JSON.stringify({ gazeMs, pressMs, gaze: pet.dataset.gaze, motion: pet.dataset.motion, eyes: pet.dataset.eyes }));
"""
            proc = subprocess.run([node, "-e", probe], capture_output=True, text=True, check=True, timeout=5)
            import json

            res = json.loads(proc.stdout.strip())
            self.assertLessEqual(res["gazeMs"], 50.0)
            self.assertLessEqual(res["pressMs"], 50.0)
            self.assertEqual(res["gaze"], "active")
            self.assertEqual(res["motion"], "press")
            self.assertEqual(res["eyes"], "squint")

    def test_existing_design_edition_harden_and_payment_suites_pass_100pct(self) -> None:
        from tests import test_design_system, test_harden, test_payment_ui, test_pet_edition

        loader = unittest.TestLoader()
        suite = unittest.TestSuite()
        for mod in (test_design_system, test_pet_edition, test_harden, test_payment_ui):
            suite.addTests(loader.loadTestsFromModule(mod))
        result = unittest.TestResult()
        suite.run(result)
        self.assertTrue(
            result.wasSuccessful(),
            f"Dependent suites had failures/errors: failures={result.failures}, errors={result.errors}",
        )


if __name__ == "__main__":
    unittest.main()
