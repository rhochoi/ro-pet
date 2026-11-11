# ro.bot pet

A small desktop pet made of three layers and two eyes. It is only for decorating your Mac: it does not read your files or record anything. The only thing it contacts is GitHub, once a day, to check for a new version (the installed app only; nothing about you is sent).

- Two materials: **Clay** and **Glass** (on macOS 26 the glass refracts what is behind it)
- Body color: System, Light, Dark, Orange; panel color: System, Light, Dark
- Three sizes: Small, Medium, Big
- Six expressions and fourteen motions to play with (press, startle, drag, shake, land …)
- Drag it anywhere, drag it to the top to send it to the menu bar, and let it wander along the bottom of the screen
- No dependencies. Python standard library plus one Swift file. The pet itself talks only to `127.0.0.1`.

## Install (macOS app)

1. Download the latest `ro-pet-<version>.dmg` from the Releases page and open it.
2. Drag **ro** onto **Applications**, then open it from Applications. It lives in the menu bar (no Dock icon).

Apple Silicon (M1 or later) only. Releases that are not notarized show a warning the first time, because the app is not signed with a paid Apple Developer ID. The pet is safe to run: the source is in this repository, it talks only to `127.0.0.1`, and the app contacts GitHub only to check for updates. To open it anyway:

- **macOS 15 or later:** double-click the app, click **Done** on the warning, open **System Settings → Privacy & Security**, scroll down, click **Open Anyway** next to "ro", and confirm.
- **macOS 13–14:** right-click (or Control-click) the app, choose **Open**, then **Open** again.
- **Terminal alternative:** `xattr -dr com.apple.quarantine /Applications/ro.app`

Not on Apple Silicon, or prefer no installer? Use the commands below.

## Run

macOS (needs Xcode command line tools for `swiftc`):

```bash
python3 -m ro_pet
```

Any OS, in a browser tab (no overlay, no menu bar):

```bash
python3 -m ro_pet --browser
```

Options: `--no-wander`, `--port N`, `--build-only`.

Click the pet to open the panel, right-click it for the menu. Settings are saved to `~/.ro-pet/config.json` (override the folder with `RO_PET_HOME`).

## Build a DMG (macOS, Apple Silicon)

Bundles the Swift host and a standalone Python, so users need neither. Needs `swiftc` and [`uv`](https://astral.sh/uv).

```bash
./scripts/build-dmg.sh    # build/ro-pet-<version>.dmg, ad-hoc signed (friends only)
```

For public release, sign with a Developer ID certificate and notarize (credentials stay in your keychain):

```bash
xcrun notarytool store-credentials "ro-notary"    # once
SIGN_IDENTITY="Developer ID Application: Name (TEAMID)" NOTARY_PROFILE=ro-notary ./scripts/build-dmg.sh
```

## Updates and releases

The installed app updates itself with [Sparkle](https://sparkle-project.org): once a day it reads `appcast.xml` from the latest release of this repository and, if a newer version exists, downloads and installs it and reopens. "Check for updates…" in the menu does it right away.

To publish a release (the maintainer's machine; the update-signing key stays in the keychain):

```bash
APP_VERSION=0.3.2 SIGN_IDENTITY="Developer ID Application: Name (TEAMID)" NOTARY_PROFILE=ro-notary ./scripts/build-dmg.sh
./scripts/make-appcast.sh build/ro-pet-0.3.2.dmg      # build/appcast.xml (editing the DMG afterwards breaks the signature)
gh release create v0.3.2 build/ro-pet-0.3.2.dmg build/appcast.xml --repo rhochoi/ro-pet --title "ro pet v0.3.2" --notes "..."
```

`APP_VERSION` must be bigger than the last release: Sparkle compares that number.

## Test

```bash
python3 -m unittest discover -s tests -t .
```

## Layout

| Path | What |
|---|---|
| `ro_pet/server.py` | Loopback web server: state, saved look, motion trigger |
| `ro_pet/page.html` | The whole pet UI (HTML, CSS, JS) |
| `ro_pet/pet_mac.swift` | macOS host: transparent window, menu bar icon, native glass, size, login item, Sparkle updates |
| `assets/icon/` | App icon (`ro.svg` source, `ro.icns` built from it) |
| `scripts/` | `build-app.sh`, `build-dmg.sh` (sign, notarize), `make-appcast.sh` (update list) |
