# ro

A local-first desktop pet and Mac assistant made of three layers and two eyes.

- **Free (`mini`)**: Desktop pet with **Clay** and **Glass** materials (native macOS 26 refraction), 4 body colors, 3 sizes, 6 expressions, 14 motions, screen-bottom wandering, app reactions, and menu bar mode.
- **Licensed (`pro`)**: Unlocks full `ro` features inside the same app — ask for files by name, date, or inside text (`⌥R`, including offline Vision OCR), tidy Downloads with one-step undo (holding folder, never hard-deleted), hand off work between AI tools (Claude Code, Codex, Antigravity), and manage shared AI rules & safety hooks.

## Privacy & Network Scope

All files, search indexes, OCR, logs, and activity stay strictly on your Mac (`~/.ro`).

- **App updates**: The packaged macOS app checks GitHub Releases once a day via Sparkle (`appcast.xml`). Nothing about you is sent.
- **Pro license auto-pickup (`ro/licensenet.py`)**: The **only** file in `ro/` allowed to make outbound requests (verified automatically by `ro/harden.py`). When you start checkout from inside ro (`Upgrade to Pro` / `Get pro…`) or while Pro is active (once a day for renewal), it sends **only** a random per-Mac install ID to the license issuer — never files, paths, names, or email. You can turn this off anytime in **License → Get my key automatically**. Keys are never typed or pasted by hand; the issued key is signature-checked offline on this Mac before it is saved.

## Install (macOS App — Recommended)

1. Download the latest `ro-pet-<version>.dmg` from the [Releases](https://github.com/rhochoi/ro-pet/releases/latest) page and open it.
2. Drag **ro** onto **Applications**, then open it from Applications. It runs in the menu bar (no Dock icon).

Apple Silicon (M1 or later) and macOS 13+ required. The packaged app bundles a standalone Python runtime, the precompiled Swift pet host, the precompiled Vision OCR helper, and Sparkle auto-updates — no Python or Xcode needed.

To unlock **ro pro**, click the pet to open the panel → **Upgrade to Pro**, or use the menu bar icon → **Get pro…**. Pro turns on by itself after payment — no key to paste.

## Run from Source / CLI

Requires Python 3.11+ (macOS needs Xcode Command Line Tools for `swiftc` when running from source):

```bash
python3 -m ro pet           # Desktop pet + menu bar overlay (macOS)
python3 -m ro pet --browser # Browser mode (any OS)
python3 -m ro_pet           # Compatibility alias
python3 -m ro --help        # Full CLI (find, organize, tidy, handoff, connect, license, ...)
```

Install the CLI globally via `uv`:

```bash
curl -fsSL https://raw.githubusercontent.com/rhochoi/ro-pet/main/install.sh | bash
```

## Build & Commercial Release (macOS, Apple Silicon)

Needs `swiftc` and [`uv`](https://astral.sh/uv).

```bash
# 1. Run preflight checks (tests, network guard, release config)
./scripts/release-preflight.sh

# 2. Local verification DMG (ad-hoc signed, this Mac only)
./scripts/build-dmg.sh

# 3. Signed & notarized commercial DMG + Sparkle appcast
APP_VERSION=0.4.0 \
  SIGN_IDENTITY="Developer ID Application: Name (TEAMID)" \
  NOTARY_PROFILE=ro-notary \
  RO_LICENSE_ISSUER="https://license.yourdomain.com" \
  ./scripts/build-dmg.sh
./scripts/make-appcast.sh build/ro-pet-0.4.0.dmg
```

See [docs/RELEASE-CHECKLIST.md](docs/RELEASE-CHECKLIST.md) for the complete end-to-end commercial launch checklist (Polar checkout, Cloudflare Worker issuer, Resend email, custom domain, Apple notarization, Sparkle updates, and GitHub Pages).

## Test

```bash
pytest -q
```

## Layout

| Path | What |
|---|---|
| `ro/` | Full `ro` package: desktop pet (`pet.py`, `pet_mac.swift`, `pet_ui/`), file search & OCR (`find*.py`, `ocr.py`, `ocr_mac.swift`), Downloads organizer (`organize.py`, `staging.py`, `journal.py`), AI handoff (`handoff.py`, `engines.py`), offline Ed25519 licensing (`license.py`, `_ed25519.py`), scoped auto-pickup (`licensenet.py`), security guards (`harden.py`, `fsguard.py`) |
| `ro_pet/` | Thin backward-compatibility entry point (`python3 -m ro_pet`) forwarding to `ro.pet` |
| `site/` | Zero-tracker static website (`/`, `/pro/`, `/thanks/`, `/license/`, `/privacy/`, `/terms/`, `/refund/`) |
| `issuer/` | Cloudflare Worker license issuer (Polar checkout + webhook signature verification + Ed25519 signing + KV + Resend email) |
| `scripts/` | `build-app.sh`, `build-dmg.sh`, `make-appcast.sh`, `license-tool.py`, `release-preflight.sh` |
| `identity/` | Shared principles used by `ro connect` / `ro.adapters` |
| `tests/` | Full unit, security, site, issuer, design-system, and payment UI test suite |
