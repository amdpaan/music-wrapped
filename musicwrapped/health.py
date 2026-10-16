"""Health checks: is everything running, and is anything silently failing?

Run by the daily snapshot job (notifies only when something is wrong) and shown by `status`.
"""

import json
import os
import subprocess
import time
from datetime import datetime, timezone

from . import paths

AGENTS = ("logger", "hourly", "snapshot", "weekly", "monthly", "yearly")
DAY = 86400


def _launchd(label):
    """'running', 'loaded' or None (not loaded)."""
    r = subprocess.run(["launchctl", "print", f"gui/{os.getuid()}/com.musicwrapped.{label}"],
                       capture_output=True, text=True)
    if r.returncode != 0:
        return None
    return "running" if "state = running" in r.stdout else "loaded"


def _recent_lines(name, since, needles):
    """Log lines newer than `since` (unix s) containing any needle. Lines start with a timestamp."""
    f = paths.LOGS / name
    if not f.exists():
        return []
    out = []
    for line in f.read_text(errors="replace").splitlines()[-2000:]:
        if not any(n in line for n in needles):
            continue
        stamp = line.split(" ", 2)
        try:
            if "T" in stamp[0]:  # Swift logger: 2026-10-17T01:05:21Z
                ts = datetime.strptime(stamp[0], "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=timezone.utc).timestamp()
            else:                # Python: 2026-10-17 01:05:21
                ts = datetime.strptime(f"{stamp[0]} {stamp[1]}", "%Y-%m-%d %H:%M:%S").timestamp()
        except (ValueError, IndexError):
            continue
        if ts >= since:
            out.append(line.strip())
    return out


def check(con, now=None):
    """Returns [(ok, what, detail)]."""
    now = now or time.time()
    res = []

    states = {a: _launchd(a) for a in AGENTS}
    missing = [a for a, s in states.items() if s is None]
    res.append((not missing, "Scheduled jobs",
                f"all {len(AGENTS)} loaded" if not missing else f"not loaded: {', '.join(missing)}. Re-run ./install.sh"))
    if states["logger"] is not None:
        res.append((states["logger"] == "running", "Logger",
                    "running" if states["logger"] == "running" else "loaded but not running. Re-run ./install.sh"))

    errors = _recent_lines("logger.log", now - DAY, ("insert failed", "sqlite:", "could not"))
    res.append((not errors, "Logger errors (24 h)",
                "none" if not errors else f"{len(errors)}, latest: {errors[-1][:140]}"))

    last_snap = con.execute("SELECT MAX(ts) FROM snapshots").fetchone()[0]
    failed = _recent_lines("snapshot.log", now - 2 * DAY, ("snapshot failed",))
    snap_ok = last_snap is not None and now - last_snap < 2 * DAY and not failed
    detail = "never" if last_snap is None else f"last {datetime.fromtimestamp(last_snap):%-d %b %H:%M}"
    if failed:
        detail += f"; failed: {failed[-1][:140]}"
    elif not snap_ok:
        detail += (" (over 2 days ago)" if last_snap else "") + ". Check the 'control Music' permission"
    res.append((snap_ok, "Daily snapshot", detail))

    try:
        hb = json.loads((paths.SUPPORT / "heartbeat.json").read_text())["last_playing_ts"]
    except (OSError, ValueError, KeyError):
        hb = None
    last_mac = con.execute("SELECT MAX(ended_ts) FROM plays WHERE source='mac'").fetchone()[0]
    silent = hb is not None and now - hb < 3 * DAY and (last_mac is None or now - last_mac > 3 * DAY)
    res.append((not silent, "Mac logging",
                "Music played on this Mac recently, but no play has been logged for 3+ days. Run: music-wrapped doctor"
                if silent else (f"last play {datetime.fromtimestamp(last_mac):%-d %b %H:%M}" if last_mac else "no plays yet")))

    backups = sorted((paths.SUPPORT / "backups").glob("plays-*.db"), key=lambda p: p.stat().st_mtime)
    newest = backups[-1].stat().st_mtime if backups else None
    res.append((newest is not None and now - newest < 8 * DAY, "Backup",
                f"last {datetime.fromtimestamp(newest):%-d %b}" if newest else "none yet. Run: music-wrapped backup"))
    return res


def report(results):
    return "\n".join(f"{'✓' if ok else '✗'} {what}: {detail}" for ok, what, detail in results)


def problems(results):
    return [(what, detail) for ok, what, detail in results if not ok]
