"""music-wrapped serve: share the reports folder over Wi-Fi so an iPhone on the same network can open them.

Runs in the foreground only while you want it (Ctrl-C, or it stops by itself after --hours). Only the
reports folder is served, read-only, under a secret path (http://<mac>.local:<port>/<code>/) kept in
config.json, so a Home Screen bookmark keeps working; `--new-link` makes a new code and the old link
stops working. No directory listings, nothing outside the reports.
"""

import hmac
import json
import secrets
import socket
import subprocess
import sys
import threading
import time
from functools import partial
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import unquote, urlsplit

from . import paths


def _config():
    try:
        return json.loads(paths.CONFIG.read_text())
    except (OSError, ValueError):
        return {}


def link_code(new=False):
    """The secret path segment, created once and kept in config.json."""
    cfg = _config()
    if new or not cfg.get("serve_code"):
        cfg["serve_code"] = secrets.token_urlsafe(6)
        paths.CONFIG.parent.mkdir(parents=True, exist_ok=True)
        paths.CONFIG.write_text(json.dumps(cfg, indent=2))
    return cfg["serve_code"]


def hostnames():
    """Names the iPhone can use: the Mac's Bonjour name (.local) and its Wi-Fi IP address."""
    out = []
    try:
        name = subprocess.run(["scutil", "--get", "LocalHostName"], capture_output=True, text=True, timeout=5).stdout.strip()
        if name:
            out.append(f"{name}.local")
    except (OSError, subprocess.SubprocessError):
        pass
    for iface in ("en0", "en1"):
        try:
            ip = subprocess.run(["ipconfig", "getifaddr", iface], capture_output=True, text=True, timeout=5).stdout.strip()
        except (OSError, subprocess.SubprocessError):
            ip = ""
        if ip:
            out.append(ip)
            break
    return out or [socket.gethostname()]


def qr(text):
    """The text as a QR code for the terminal (black on white, two rows per line), or None if it can't
    be made. Drawn by macOS (CoreImage) through the story renderer's --qr mode."""
    from .story import renderer
    try:
        out = subprocess.run([str(renderer()), "--qr", text], capture_output=True, text=True, timeout=60, check=True).stdout
    except (OSError, subprocess.SubprocessError):
        return None
    rows = [r for r in out.split() if r]
    if not rows:
        return None
    pad = 2                                            # quiet zone, in modules
    w = len(rows[0]) + 2 * pad
    grid = [[False] * w] * pad + [[False] * pad + [c == "1" for c in r] + [False] * pad for r in rows] + [[False] * w] * pad
    if len(grid) % 2:
        grid.append([False] * w)
    chars = {(True, True): "█", (True, False): "▀", (False, True): "▄", (False, False): " "}
    lines = ["".join(chars[(a, b)] for a, b in zip(grid[i], grid[i + 1])) for i in range(0, len(grid), 2)]
    return "\n".join(f"  \033[30;107m{line}\033[0m" for line in lines)


class Handler(SimpleHTTPRequestHandler):
    code = ""

    def _strip(self):
        """The path without /<code>, or None if the code is missing or wrong."""
        path = urlsplit(self.path).path
        prefix = f"/{self.code}"
        head = path[:len(prefix)]
        if not hmac.compare_digest(head.encode(), prefix.encode()):
            return None
        rest = path[len(prefix):]
        if rest == "":
            return ""        # redirect to the slash form so relative links work
        return rest if rest.startswith("/") else None

    def send_head(self):
        rest = self._strip()
        if rest is None:
            self.send_error(404)
            return None
        if rest == "":
            self.send_response(301)
            self.send_header("Location", f"/{self.code}/")
            self.end_headers()
            return None
        target = paths.REPORTS / unquote(rest).lstrip("/")
        if target.is_dir():
            if not rest.endswith("/"):
                self.send_response(301)
                self.send_header("Location", f"/{self.code}{rest}/")
                self.end_headers()
                return None
            if not (target / "index.html").exists():
                self.send_error(404)     # no folder listings
                return None
        self.path = rest
        return super().send_head()

    def list_directory(self, path):
        self.send_error(404)
        return None

    def end_headers(self):
        # Always fresh: the weekly page changes after every play.
        self.send_header("Cache-Control", "no-store")
        self.send_header("X-Content-Type-Options", "nosniff")
        self.send_header("Referrer-Policy", "no-referrer")
        super().end_headers()

    def log_message(self, fmt, *args):
        pass


def run(port=8000, hours=2.0, new_link=False, copy=True):
    sys.stdout.reconfigure(line_buffering=True)  # show the link at once, even when piped
    if not (paths.REPORTS / "index.html").exists():
        print("No reports yet. Make one first: music-wrapped report weekly")
        return 1
    code = link_code(new_link)
    handler = partial(type("H", (Handler,), {"code": code}), directory=str(paths.REPORTS))
    try:
        server = ThreadingHTTPServer(("0.0.0.0", port), handler)
    except OSError as ex:
        print(f"Can't use port {port} ({ex.strerror}). Try: music-wrapped serve --port 8123")
        return 1
    urls = [f"http://{h}:{port}/{code}/" for h in hostnames()]
    code_art = qr(urls[0])
    if code_art:
        print("Your reports are open to devices on this Wi-Fi. Scan this with your iPhone's camera:\n")
        print(code_art)
        print("\nOr open in Safari:")
    else:
        print("Your reports are open to devices on this Wi-Fi. On your iPhone, open in Safari:\n")
    for u in urls:
        print(f"  {u}")
    if copy:
        subprocess.run(["pbcopy"], input=urls[0].encode(), check=False)
        print("\n(Copied. With Handoff on, you can paste it on your iPhone straight away.)")
    print(f"\nTip: Share → Add to Home Screen. Stops in {hours:g} h, or press Ctrl-C."
          "\nAnyone on this network with the link can see your reports; `--new-link` changes it.")
    timer = threading.Timer(hours * 3600, server.shutdown) if hours > 0 else None
    if timer:
        timer.daemon = True
        timer.start()
    started = time.time()
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        if timer:
            timer.cancel()
        server.server_close()
    print(f"\nStopped after {round((time.time() - started) / 60)} min. Nothing is shared now.")
    return 0
