"""Local-only web server for the pet UI. Standard library only; binds to 127.0.0.1."""
import hashlib
import hmac
import json
import os
import secrets
import tempfile
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlparse

HOME = Path(os.environ.get("RO_PET_HOME", "~/.ro-pet")).expanduser()
PAGE = Path(__file__).with_name("page.html")

MOODS = ("idle", "recording", "focus", "anxious", "discovery", "resolved")
ACTIONS = ("press", "breathe", "look_around", "walk", "thinking", "alert", "drowsy", "gaze",
           "pet", "drag", "shake", "drop", "success", "failure")
TINT_PRESETS = {"sage": "#8FB39A", "sky": "#8EBBE0", "lilac": "#B7A4E0"}
PREF_CHOICES = {
    "material": ("clay", "glass"),
    "theme": ("auto", "ink", "chalk"),
    "glass": ("auto", "light", "dark"),
    "tint": ("none", *TINT_PRESETS),
}
MAX_ACTION_SEC = 60.0
STATE_WAIT_TIMEOUT = 20.0
STATE_WAIT_INTERVAL = 1.0


def ambient_label(hour):
    return "Morning" if hour < 12 else ("Afternoon" if hour < 18 else "Evening")


class Pet:
    """Pet state: saved look settings and the current motion."""

    def __init__(self, home=HOME):
        self.home = Path(home)
        self.token = secrets.token_hex(16)
        self._lock = threading.Lock()
        self.action = None
        self.action_until = 0.0

    @property
    def _config_path(self):
        return self.home / "config.json"

    def prefs(self):
        try:
            data = json.loads(self._config_path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return {}
        return {k: v for k, v in data.items() if v in PREF_CHOICES.get(k, ())} if isinstance(data, dict) else {}

    def set_prefs(self, changes):
        clean = {k: v for k, v in (changes or {}).items() if v in PREF_CHOICES.get(k, ())}
        if not clean:
            return {"ok": False, "error": "That setting cannot be saved."}
        merged = {**self.prefs(), **clean}
        self.home.mkdir(parents=True, exist_ok=True)
        fd, tmp = tempfile.mkstemp(dir=self.home, prefix=".config-")
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            json.dump(merged, f)
        os.replace(tmp, self._config_path)
        return {"ok": True, "prefs": merged}

    def trigger_action(self, action, duration=4.0):
        if action not in ACTIONS:
            return {"ok": False, "error": f"Unsupported motion: {action}"}
        try:
            duration = float(duration)
        except (TypeError, ValueError):
            return {"ok": False, "error": "duration must be a number."}
        if not 0 < duration <= MAX_ACTION_SEC:
            return {"ok": False, "error": f"duration must be between 0 and {MAX_ACTION_SEC:g} seconds."}
        with self._lock:
            self.action = action
            self.action_until = time.time() + duration
        return {"ok": True, "action": action, "duration": duration}

    def snapshot(self, now=None):
        now = now or time.time()
        with self._lock:
            action = self.action if now < self.action_until else None
        label = ambient_label(time.localtime(now).tm_hour)
        return {"mood": "idle", "action": action, "prefs": self.prefs(),
                "ambient": {"label": label, "focus": False, "held": 0, "attention": False}}


def render_html(token, prefs=None):
    p = {k: v for k, v in (prefs or {}).items() if v in PREF_CHOICES.get(k, ())}
    return (PAGE.read_text(encoding="utf-8").replace("__RO_TOKEN__", token)
            .replace("__RO_PREFS__", json.dumps(p)).replace("__RO_TINT_PRESETS__", json.dumps(TINT_PRESETS)))


def make_handler(pet):
    class Handler(BaseHTTPRequestHandler):
        def log_message(self, fmt, *args):
            return

        def _send(self, status, body, ctype):
            self.send_response(status)
            self.send_header("Content-Type", ctype)
            self.send_header("Cache-Control", "no-store")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def _json(self, status, payload):
            self._send(status, json.dumps(payload).encode("utf-8"), "application/json; charset=utf-8")

        def _allowed(self):
            # Block DNS rebinding: only answer requests addressed to the loopback host name we bound.
            port = self.server.server_address[1]
            if self.headers.get("Host", "") not in (f"127.0.0.1:{port}", f"localhost:{port}"):
                self._json(403, {"ok": False, "error": "invalid host"})
                return False
            return True

        def _authed(self):
            if hmac.compare_digest(self.headers.get("X-Ro-Token", ""), pet.token):
                return True
            self._json(403, {"ok": False, "error": "invalid token"})
            return False

        def do_GET(self):
            if not self._allowed():
                return
            url = urlparse(self.path)
            if url.path == "/":
                self._send(200, render_html(pet.token, pet.prefs()).encode("utf-8"), "text/html; charset=utf-8")
            elif url.path == "/api/state":
                if not self._authed():
                    return
                wait = parse_qs(url.query).get("wait", [None])[0]
                deadline = time.monotonic() + STATE_WAIT_TIMEOUT
                while True:
                    snap = pet.snapshot()
                    version = hashlib.sha256(json.dumps(snap, sort_keys=True).encode()).hexdigest()[:16]
                    remaining = deadline - time.monotonic()
                    if wait != version or remaining <= 0:
                        try:
                            self._json(200, {**snap, "version": version})
                        except (BrokenPipeError, ConnectionResetError):
                            pass
                        return
                    time.sleep(min(STATE_WAIT_INTERVAL, remaining))
            else:
                self._json(404, {"ok": False, "error": "not found"})

        def do_POST(self):
            if not (self._allowed() and self._authed()):
                return
            length = int(self.headers.get("Content-Length", "0") or "0")
            raw = self.rfile.read(min(length, 8192)).decode("utf-8", errors="replace")
            try:
                data = json.loads(raw) if raw else {}
            except ValueError:
                data = None
            if not isinstance(data, dict):
                self._json(400, {"ok": False, "error": "a JSON object is required"})
                return
            path = urlparse(self.path).path
            if path == "/api/prefs":
                self._json(200, pet.set_prefs(data))
            elif path == "/api/action":
                self._json(200, pet.trigger_action(data.get("action") or data.get("name", ""),
                                                   data.get("duration", 4.0)))
            else:
                self._json(404, {"ok": False, "error": "not found"})

    return Handler


def start_server(pet, port=0):
    server = ThreadingHTTPServer(("127.0.0.1", port), make_handler(pet))
    server.daemon_threads = True
    threading.Thread(target=server.serve_forever, daemon=True).start()
    return server
