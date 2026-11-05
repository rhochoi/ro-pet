"""Run the pet: `python3 -m ro_pet` (macOS desktop overlay) or `python3 -m ro_pet --browser`."""
import argparse
import os
import shutil
import signal
import subprocess
import sys
import tempfile
import time
import webbrowser
from pathlib import Path

from .server import Pet, start_server

SWIFT_SRC = Path(__file__).with_name("pet_mac.swift")


def ensure_mac_binary(force=False):
    """Return the macOS host binary. An app bundle passes a prebuilt one in RO_PET_HOST (no swiftc needed).
    Otherwise compile the Swift host once and cache it. Returns None when swiftc is not available."""
    prebuilt = os.environ.get("RO_PET_HOST")
    if prebuilt and not force and os.access(prebuilt, os.X_OK):
        return Path(prebuilt)
    if not SWIFT_SRC.exists() or not shutil.which("swiftc"):
        return None
    cache = Path(tempfile.gettempdir()) / f"ro-pet-{os.getuid()}"
    cache.mkdir(parents=True, exist_ok=True)
    binary = cache / "ro-pet-host"
    if not force and binary.exists() and binary.stat().st_mtime >= SWIFT_SRC.stat().st_mtime:
        return binary
    cmd = ["swiftc", "-O", str(SWIFT_SRC), "-o", str(binary), "-framework", "AppKit", "-framework", "WebKit"]
    result = subprocess.run(cmd, capture_output=True, text=True, timeout=120)
    if result.returncode != 0:
        raise RuntimeError(f"Could not compile the macOS host:\n{result.stderr}")
    binary.chmod(0o700)
    return binary


def main(argv=None):
    ap = argparse.ArgumentParser(prog="ro-pet", description=__doc__)
    ap.add_argument("--browser", action="store_true", help="open in a browser tab instead of a desktop overlay")
    ap.add_argument("--no-wander", action="store_true", help="do not let the pet stroll along the screen bottom")
    ap.add_argument("--port", type=int, default=0, help="local port (default: any free port)")
    ap.add_argument("--build-only", action="store_true", help="compile the macOS host and exit")
    args = ap.parse_args(argv)

    if args.build_only:
        binary = ensure_mac_binary(force=True)
        print(binary or "swiftc not found")
        return 0 if binary else 1

    pet = Pet()
    server = start_server(pet, args.port)
    url = f"http://127.0.0.1:{server.server_address[1]}/"
    host = None
    try:
        binary = None if args.browser or sys.platform != "darwin" else ensure_mac_binary()
        if binary:
            cmd = [str(binary), "--url", url] + ([] if args.no_wander else ["--wander"])
            print(f"ro pet running: {url}  (quit from the menu bar icon or Ctrl+C)")
            host = subprocess.Popen(cmd)
            signal.signal(signal.SIGTERM, lambda *_: (host.terminate(), sys.exit(0)))
            host.wait()
        else:
            print(f"ro pet running in the browser: {url}  (quit: Ctrl+C)")
            webbrowser.open(url)
            while True:
                time.sleep(1)
    except KeyboardInterrupt:
        pass
    finally:
        if host and host.poll() is None:
            host.terminate()
        server.shutdown()
        server.server_close()
    return 0


if __name__ == "__main__":
    sys.exit(main())
