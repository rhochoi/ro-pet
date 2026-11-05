# ro.bot pet

A small desktop pet made of three layers and two eyes. It is only for decorating your Mac: it does not read your files, record anything or talk to any service.

- Two materials: **Clay** and **Glass** (on macOS 26 the glass refracts what is behind it)
- Body colors: System, Light, Dark, Sage, Sky, Lilac
- Six expressions and fourteen motions to play with (press, startle, drag, shake, land …)
- Drag it anywhere, drag it to the top to send it to the menu bar, and let it wander along the bottom of the screen
- No dependencies. Python standard library plus one Swift file. Everything stays on `127.0.0.1`.

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

## Test

```bash
python3 -m unittest discover -s tests -t .
```

## Layout

| Path | What |
|---|---|
| `ro_pet/server.py` | Loopback web server: state, saved look, motion trigger |
| `ro_pet/page.html` | The whole pet UI (HTML, CSS, JS) |
| `ro_pet/pet_mac.swift` | macOS host: transparent window, menu bar icon, native glass |
