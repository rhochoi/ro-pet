"""Run the pet: `python3 -m ro_pet` (macOS desktop overlay) or `python3 -m ro_pet --browser`."""
import argparse
import sys

from ro import license as license_mod
from ro import pet


def main(argv=None):
    ap = argparse.ArgumentParser(prog="ro-pet", description=__doc__)
    ap.add_argument("--browser", action="store_true", help="open in a browser tab instead of a desktop overlay")
    ap.add_argument("--no-wander", action="store_true", help="do not let the pet stroll along the screen bottom")
    ap.add_argument("--port", type=int, default=0, help="local port (default: any free port)")
    ap.add_argument("--build-only", action="store_true", help="compile the macOS host and exit")
    args = ap.parse_args(argv)

    license_mod.apply_edition_from_license()
    res = pet.launch(
        port=args.port,
        mode="browser" if args.browser else "overlay",
        wander=not args.no_wander,
        build_only=args.build_only,
    )
    if args.build_only:
        print(res or "swiftc not found")
        return 0 if res else 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
