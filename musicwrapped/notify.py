"""macOS notifications. terminal-notifier (Homebrew) makes them clickable."""

import shutil
import subprocess

EXTRA_PATH = "/opt/homebrew/bin:/usr/local/bin:/usr/bin:/bin"


def notify(title, message, path=None):
    tn = shutil.which("terminal-notifier", path=EXTRA_PATH)
    if tn:
        cmd = [tn, "-title", title, "-message", message, "-group", f"music-wrapped-{title}", "-sound", "default"]
        if path:
            cmd += ["-open", path.as_uri()]
        subprocess.run(cmd, capture_output=True, check=False)
        return
    # Fallback: shows the notification, but clicking it can't open the report.
    script = f"display notification {_q(message)} with title {_q(title)} sound name \"default\""
    subprocess.run(["osascript", "-e", script], capture_output=True, check=False)


def _q(s):
    return '"' + s.replace("\\", "\\\\").replace('"', '\\"') + '"'
