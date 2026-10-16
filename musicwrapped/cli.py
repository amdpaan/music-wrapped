"""Command line: music-wrapped <command>. Run `music-wrapped --help`."""

import argparse
import json
import subprocess
import sys
from datetime import date, datetime, timedelta
from pathlib import Path

from . import backup, db, library, notify, paths, reports, summary

LOGGER = paths.SUPPORT / "bin/music-wrapped-logger"
LOGGER_LABEL = "com.musicwrapped.logger"


def log(msg):
    print(f"{datetime.now():%Y-%m-%d %H:%M:%S} {msg}", flush=True)


def take_snapshot(kind):
    try:
        r = library.run_snapshot(kind)
        log(f"snapshot ({r['kind']}): {r['tracks']} tracks, {r['total_play_count']:,} library plays, "
            f"{r['other_plays']} new plays from other devices")
        return r
    except (library.MusicError, OSError, subprocess.SubprocessError, ValueError) as ex:
        log(f"snapshot failed: {ex}")
        return None


def open_path(p):
    subprocess.run(["open", str(p)], check=False)


# ---------- commands ----------

def cmd_snapshot(a):
    r = take_snapshot(a.kind)
    if r:
        con = db.connect()
        summary.write(con)
    return 0 if r else 1


def cmd_backfill(a):
    con = db.connect()
    if library.has_backfill(con) and not a.force:
        print("Backfill already done (the first snapshot is the backfill). Taking a normal snapshot instead.")
        return cmd_snapshot(argparse.Namespace(kind="manual"))
    return cmd_snapshot(argparse.Namespace(kind="backfill"))


def scheduled_target(kind, today):
    """Which period a scheduled run covers (robust to running late after the Mac was asleep)."""
    if kind == "weekly":
        return today if today.weekday() == 6 else today - timedelta(days=7)
    if kind == "monthly":
        first = today.replace(day=1) - timedelta(days=1)
        return first.year, first.month
    if kind == "yearly":
        return today.year if today.month == 12 else today.year - 1
    return None


def build(con, a):
    today = date.today()
    k = a.kind
    if k == "weekly":
        d = reports.parse_week(a.week) if a.week else (scheduled_target(k, today) if a.scheduled else today)
        return reports.weekly(con, d)
    if k == "monthly":
        if a.month:
            y, m = map(int, a.month.split("-"))
            return reports.monthly(con, y, m, so_far=(y, m) == (today.year, today.month))
        if a.current:
            return reports.monthly(con, today.year, today.month, so_far=True)
        y, m = scheduled_target(k, today)
        return reports.monthly(con, y, m)
    if k == "yearly":
        y = a.year or (scheduled_target(k, today) if a.scheduled else today.year)
        return reports.yearly(con, y)
    if k == "alltime":
        return reports.alltime(con)
    raise SystemExit(f"unknown report {k}")


def finish(con, kind, name, html, a, label):
    out = reports.save(kind, name, html)
    log(f"saved {out}")
    if a.scheduled:
        notify.notify("Music Wrapped", f"Your {label} is ready — click to open.", out)
    elif not a.no_open:
        open_path(out)
    return out


def cmd_report(a):
    if a.live:  # quick rebuild by the logger after each play
        a.no_snapshot = a.no_open = True
        from . import artwork
        artwork.ALLOW_LAUNCH = False
    if not a.no_snapshot:
        take_snapshot("report")
    con = db.connect()
    kind, name, html = build(con, a)
    label = {"weekly": f"weekly Wrapped ({name})", "monthly": f"monthly Wrapped ({name})",
             "yearly": f"{name} Wrapped", "alltime": "all-time Wrapped"}[kind]
    finish(con, kind, name, html, a, label)
    if kind == "weekly" and not a.live:  # all-time is refreshed with every weekly report
        k2, n2, h2 = reports.alltime(con)
        out = reports.save(k2, n2, h2)
        log(f"saved {out}")
    summary.write(con)
    if kind == "weekly" and a.scheduled:  # weekly backup
        for line in backup.run():
            log(line)
    return 0


def cmd_custom(a):
    start, end = date.fromisoformat(a.start), date.fromisoformat(a.end)
    if end < start:
        raise SystemExit("end date is before start date")
    if not a.no_snapshot:
        take_snapshot("report")
    con = db.connect()
    kind, name, html = reports.custom(con, start, end, a.name)
    finish(con, kind, name, html, a, "custom Wrapped")
    summary.write(con)
    return 0


def cmd_open(a):
    p = reports.latest(a.kind)
    if not p:
        print("No report yet. Generate one with: music-wrapped report weekly")
        return 1
    print(p)
    open_path(p)
    return 0


def cmd_backup(a):
    if a.setup_github is not None:
        name = backup.setup_github(a.setup_github or None)
        log(f"backups will be pushed to the private repo {name}")
    for line in backup.run():
        log(line)
    return 0


def cmd_home(a):
    reports.write_index()
    p = paths.REPORTS / "index.html"
    print(p)
    open_path(p)
    return 0


def cmd_summary(a):
    print(json.dumps(summary.write(db.connect()), indent=2, ensure_ascii=False))
    return 0


def cmd_status(a):
    con = db.connect()
    lt = con.execute("SELECT COUNT(*), SUM(source='mac'), SUM(source='other'), MAX(played_at) FROM plays").fetchone()
    snap = con.execute("SELECT ts, kind, tracks, total_play_count FROM snapshots ORDER BY ts DESC LIMIT 1").fetchone()
    today = con.execute("SELECT COUNT(*) FROM plays WHERE ts >= ?", (int(datetime.combine(date.today(), datetime.min.time()).timestamp()),)).fetchone()[0]
    print(f"Data folder:     {paths.SUPPORT}")
    print(f"Plays logged:    {lt[0]:,} (mac {lt[1] or 0:,}, other devices {lt[2] or 0:,}); today {today}")
    print(f"Last play:       {lt[3] or '—'}")
    if snap:
        print(f"Last snapshot:   {datetime.fromtimestamp(snap['ts']):%Y-%m-%d %H:%M} ({snap['kind']}), "
              f"{snap['tracks']:,} tracks, {snap['total_play_count']:,} library plays")
    else:
        print("Last snapshot:   none — run: music-wrapped backfill")
    cfg = _config()
    print(f"Logger mode:     {cfg.get('mode', 'notifications')}")
    r = subprocess.run(["launchctl", "list"], capture_output=True, text=True).stdout
    for label in ("logger", "snapshot", "weekly", "monthly", "yearly"):
        print(f"launchd {label + ':':9} {'loaded' if f'com.musicwrapped.{label}' in r else 'NOT loaded'}")
    for k in paths.REPORT_KINDS:
        p = reports.latest(k)
        print(f"latest {k + ':':10} {p if p else '—'}")
    return 0


def _config():
    try:
        return json.loads(paths.CONFIG.read_text())
    except (OSError, ValueError):
        return {}


def _set_mode(mode):
    cfg = _config()
    cfg["mode"] = mode
    paths.CONFIG.write_text(json.dumps(cfg, indent=2))
    import os
    subprocess.run(["launchctl", "kickstart", "-k", f"gui/{os.getuid()}/{LOGGER_LABEL}"], capture_output=True)
    print(f"Logger mode set to {mode} (logger restarted).")


def cmd_mode(a):
    _set_mode(a.mode)
    return 0


def cmd_doctor(a):
    """Checks that Music's track-change notifications reach us; offers poll mode if not."""
    exe = LOGGER if LOGGER.exists() else Path(__file__).resolve().parent.parent / "build/music-wrapped-logger"
    if not exe.exists():
        print("Logger not built yet. Run ./install.sh first.")
        return 1
    r = subprocess.run([str(exe), "--probe", str(a.seconds)])
    if r.returncode == 0:
        print("✓ Notifications work. The logger stays in event-driven mode (no polling).")
        if _config().get("mode") == "poll":
            _set_mode("notifications")
        return 0
    print("✗ No notifications received. (Did you play/pause something in Music during the test?)")
    if input("Switch the logger to 30-second polling? [y/N] ").strip().lower() == "y":
        _set_mode("poll")
        print("Poll mode uses AppleScript: approve the 'control Music' prompt for music-wrapped-logger if asked.")
    return 2


def cmd_demo(a):
    from . import demo
    con = demo.build()
    today = date.today()
    outs = [reports.save(*reports.weekly(con, today)),
            reports.save(*reports.monthly(con, today.year, today.month, so_far=True)),
            reports.save(*reports.yearly(con, today.year)),
            reports.save(*reports.alltime(con)),
            reports.save(*reports.custom(con, today - timedelta(days=60), today, "Demo semester"))]
    summary.write(con)
    for o in outs:
        print(o)
    if not a.no_open:
        for o in outs:
            open_path(o)
    return 0


def main(argv=None):
    p = argparse.ArgumentParser(prog="music-wrapped", description="Personal Apple Music Wrapped.")
    sub = p.add_subparsers(dest="cmd", required=True)

    s = sub.add_parser("backfill", help="first-time library import (all-time stats)")
    s.add_argument("--force", action="store_true", help="snapshot even if a backfill exists")
    s.set_defaults(fn=cmd_backfill)

    s = sub.add_parser("snapshot", help="snapshot library play counts (finds plays from other devices)")
    s.add_argument("--kind", default="manual", choices=["manual", "daily", "report"])
    s.set_defaults(fn=cmd_snapshot)

    s = sub.add_parser("report", help="generate a weekly / monthly / yearly / alltime report")
    s.add_argument("kind", choices=["weekly", "monthly", "yearly", "alltime"])
    s.add_argument("--week", help="weekly: ISO week, e.g. 2026-W42 (default: this week)")
    s.add_argument("--month", help="monthly: YYYY-MM (default: last month)")
    s.add_argument("--current", action="store_true", help="monthly: this month so far")
    s.add_argument("--year", type=int, help="yearly: year (default: this year, Jan–Nov)")
    s.add_argument("--scheduled", action="store_true", help=argparse.SUPPRESS)
    s.add_argument("--live", action="store_true", help=argparse.SUPPRESS)
    s.add_argument("--no-open", action="store_true", help="don't open the browser")
    s.add_argument("--no-snapshot", action="store_true", help="skip the library snapshot first")
    s.set_defaults(fn=cmd_report)

    s = sub.add_parser("custom", help="report for any date range, e.g. custom 2026-09-01 2026-12-31 --name 'Semester 1'")
    s.add_argument("start", help="YYYY-MM-DD")
    s.add_argument("end", help="YYYY-MM-DD (inclusive)")
    s.add_argument("--name", help="title, also used in the file name")
    s.add_argument("--no-open", action="store_true")
    s.add_argument("--no-snapshot", action="store_true")
    s.set_defaults(fn=cmd_custom, scheduled=False)

    s = sub.add_parser("open", help="open the latest report (optionally of one kind)")
    s.add_argument("kind", nargs="?", choices=paths.REPORT_KINDS)
    s.set_defaults(fn=cmd_open)

    s = sub.add_parser("backup", help="back up plays.db (also runs every Sunday with the weekly report)")
    s.add_argument("--setup-github", nargs="?", const="", metavar="REPO",
                   help="create/use a PRIVATE GitHub repo for backups (default: <you>/music-wrapped-data)")
    s.set_defaults(fn=cmd_backup)

    s = sub.add_parser("home", help="open the page listing every report")
    s.set_defaults(fn=cmd_home)

    s = sub.add_parser("summary", help="rewrite summary.json for the widget and print it")
    s.set_defaults(fn=cmd_summary)

    s = sub.add_parser("status", help="show what's logged and what's running")
    s.set_defaults(fn=cmd_status)

    s = sub.add_parser("doctor", help="check that Music's track-change notifications arrive")
    s.add_argument("--seconds", type=int, default=45)
    s.set_defaults(fn=cmd_doctor)

    s = sub.add_parser("mode", help="switch the logger between notifications and 30 s polling")
    s.add_argument("mode", choices=["notifications", "poll"])
    s.set_defaults(fn=cmd_mode)

    s = sub.add_parser("demo", help="preview all reports with fake data (separate demo folder)")
    s.add_argument("--no-open", action="store_true")
    s.set_defaults(fn=cmd_demo)

    a = p.parse_args(argv)
    sys.exit(a.fn(a))
