"""Library snapshots via AppleScript (JXA): the backfill and the iPhone/other-device plays.

Every snapshot reads play count, last played, date added, title, artist, album and
duration for every library track, in one bulk call. The first snapshot is the backfill
(all-time stats only). Later snapshots compare play counts with the previous one: an
increase that the Mac logger doesn't explain becomes `source = 'other'` plays. A track seen for the first
time (in the backfill or later) only gets a baseline: its existing play count is never counted.
"""

import json
import subprocess
from contextlib import contextmanager
import time
from datetime import datetime

from . import db

JXA = r"""
const m = Application("Music");
const t = m.libraryPlaylists[0].tracks;
const iso = d => (d ? d.toISOString() : null);
JSON.stringify({
  pid: t.persistentID(), title: t.name(), artist: t.artist(), album: t.album(),
  duration: t.duration(), plays: t.playedCount(), genre: t.genre(),
  played: t.playedDate().map(iso), added: t.dateAdded().map(iso),
});
"""

# Music bumps a track's play count only when it plays to (about) the end. A Mac play
# that stopped earlier is logged by us but isn't in the library count, so only Mac plays
# that reached this fraction of the track are subtracted from a play-count increase.
COMPLETED_FRACTION = 0.9
# A play also counts as finished if it spanned the whole track in wall-clock time (within this many
# seconds) and at least half was heard: covers listening time the logger missed while restarting.
SPAN_SLACK = 10
# A Mac play "explains" a track's new last-played date if it ended this close to it (seconds).
EXPLAIN_SLACK = 180
# How far back a new "last played" date may be and still count as a real play from another device,
# however often snapshots run (every 5 minutes while Music is open): iCloud can take a while to sync.
RECENT_WINDOW = 3600


class MusicError(RuntimeError):
    pass


def music_running():
    return subprocess.run(["pgrep", "-xq", "Music"]).returncode == 0


def _iso_to_ts(s):
    if not s:
        return None
    return int(datetime.fromisoformat(s.replace("Z", "+00:00")).timestamp())


def local_iso(ts):
    return datetime.fromtimestamp(ts).astimezone().isoformat(timespec="seconds")


@contextmanager
def music_session():
    """Starts Music hidden if it isn't running, and quits it afterwards if we started it."""
    launched = False
    if not music_running():
        subprocess.run(["open", "-g", "-j", "-a", "Music"], check=False)
        launched = True
        for _ in range(20):  # wait until it answers AppleScript
            if subprocess.run(["osascript", "-e", 'tell application "Music" to get version'],
                              capture_output=True).returncode == 0:
                break
            time.sleep(1)
    try:
        yield
    finally:
        if launched:
            subprocess.run(["osascript", "-e", 'tell application "Music" to quit'],
                           capture_output=True, check=False)


def fetch_tracks():
    """Returns every library track. Starts Music hidden if needed and quits it afterwards."""
    with music_session():
        last = ""
        for _ in range(20):
            r = subprocess.run(["osascript", "-l", "JavaScript", "-e", JXA],
                               capture_output=True, text=True, timeout=300)
            if r.returncode == 0 and r.stdout.strip():
                return _parse(json.loads(r.stdout))
            last = r.stderr.strip()
            if "-1743" in last or "Not authorized" in last:
                raise MusicError(
                    "Not allowed to control Music. Approve the Automation prompt, or enable it in "
                    "System Settings → Privacy & Security → Automation.")
            time.sleep(1.5)  # Music may still be starting up
        raise MusicError(f"Could not read the Music library: {last}")


def _parse(d):
    tracks = []
    for i, pid in enumerate(d["pid"]):
        tracks.append({
            "pid": pid.upper(),
            "title": d["title"][i] or "",
            "artist": d["artist"][i] or "",
            "album": d["album"][i] or "",
            "genre": (d["genre"][i] or "").strip(),
            "duration": float(d["duration"][i] or 0),
            "plays": int(d["plays"][i] or 0),
            "played_ts": _iso_to_ts(d["played"][i]),
            "added_ts": _iso_to_ts(d["added"][i]),
        })
    return tracks


def has_backfill(con):
    return con.execute("SELECT 1 FROM snapshots LIMIT 1").fetchone() is not None


def snapshot(con, kind="manual", tracks=None, now=None):
    """Takes a snapshot and records other-device plays. Returns a dict of what changed."""
    tracks = fetch_tracks() if tracks is None else tracks
    now = int(time.time()) if now is None else now
    prev = con.execute("SELECT MAX(ts) FROM snapshots").fetchone()[0]
    first = prev is None
    if first:
        kind = "backfill"
    known = {r["persistent_id"]: r for r in con.execute("SELECT * FROM library")}
    added_plays = 0
    ignored = 0  # play-count increases treated as iCloud catching up on old plays
    seen = set()

    with con:
        for t in tracks:
            pid = t["pid"]
            seen.add(pid)
            row = known.get(pid)
            if row is None:
                # New to us: its current play count is only a baseline, never plays for today.
                # Increases after this are counted; Mac plays already logged stay as they are.
                delta = 0
                con.execute(
                    """INSERT INTO library (persistent_id, title, artist, album, genre, duration, play_count,
                       played_ts, added_ts, baseline_play_count, first_seen_ts, updated_ts)
                       VALUES (?,?,?,?,?,?,?,?,?,?,?,?)""",
                    (pid, t["title"], t["artist"], t["album"], t["genre"], t["duration"], t["plays"],
                     t["played_ts"], t["added_ts"], t["plays"], now, now))
            else:
                delta = t["plays"] - row["play_count"]
                since = prev
                con.execute(
                    """UPDATE library SET title=?, artist=?, album=?, genre=?, duration=?, play_count=?,
                       played_ts=?, added_ts=?, updated_ts=?, in_library=1 WHERE persistent_id=?""",
                    (t["title"], t["artist"], t["album"], t["genre"], t["duration"], t["plays"],
                     t["played_ts"], t["added_ts"], now, pid))
            if delta > 0 and not first:
                added, skipped = _record_other_plays(con, t, delta, since, now)
                added_plays += added
                ignored += skipped

        missing = set(known) - seen
        con.executemany("UPDATE library SET in_library=0, updated_ts=? WHERE persistent_id=?",
                        [(now, pid) for pid in missing])
        con.execute(
            "INSERT INTO snapshots (ts, kind, tracks, total_play_count, other_plays_added) VALUES (?,?,?,?,?)",
            (now, kind, len(tracks), sum(t["plays"] for t in tracks), added_plays))

    return {"kind": kind, "tracks": len(tracks), "other_plays": added_plays, "ignored": ignored,
            "total_play_count": sum(t["plays"] for t in tracks)}


def _record_other_plays(con, t, delta, since, now):
    """Adds the part of a play-count increase that the Mac logger didn't record.

    Returns (plays added, increase ignored). iCloud can deliver a backlog of old plays from other
    devices all at once (e.g. +70 on one song). Real plays in this window also move the track's
    "last played" date into the window, so:
      - last-played date unchanged: the whole increase is old plays syncing in. Absorbed, not counted.
      - more plays than could fit in the window: a backlog plus at most one real play, which counts
        only if a Mac play doesn't explain the new last-played date.
    """
    finished = """source='mac' AND persistent_id=?
           AND (duration IS NULL OR duration = 0 OR seconds_listened >= duration * ?
                OR (ended_ts - ts >= duration - ? AND seconds_listened >= duration * 0.5))"""
    mac = con.execute(f"SELECT COUNT(*) FROM plays WHERE {finished} AND ended_ts > ? AND ended_ts <= ?",
                      (t["pid"], COMPLETED_FRACTION, SPAN_SLACK, since or 0, now)).fetchone()[0]
    other = delta - mac
    played = t["played_ts"]
    if other > 0 and since and played:
        # A Mac play that ended just before this window can have its play count land in this one
        # (Music bumps it a moment after the song ends). If it explains the new last-played date,
        # no other device played the song after it, so the increase is that Mac play: don't count it twice.
        late = con.execute(f"SELECT COUNT(*) FROM plays WHERE {finished} AND ended_ts > ? AND ended_ts <= ? "
                           "AND ABS(ended_ts - ?) <= ?",
                           (t["pid"], COMPLETED_FRACTION, SPAN_SLACK, since - EXPLAIN_SLACK, since,
                            played, EXPLAIN_SLACK)).fetchone()[0]
        other -= min(late, other)
    if other <= 0:
        return 0, 0
    # Recent enough to be a real play: at least the last hour, even when the previous snapshot was
    # only minutes ago (the Mac-play subtraction above still uses the exact window).
    lo = min(since, now - RECENT_WINDOW) if since else 0
    if not (played and lo < played <= now):
        return 0, other
    fit = max(1, int((now - lo) // max(t["duration"] or 0, 30)))
    if other > fit:
        explained = con.execute(
            "SELECT 1 FROM plays WHERE source='mac' AND persistent_id=? AND ABS(ended_ts - ?) <= ? LIMIT 1",
            (t["pid"], played, EXPLAIN_SLACK)).fetchone()
        keep = 0 if explained else 1
        ignored = other - keep
        other = keep
        if not other:
            return 0, ignored
    else:
        ignored = 0
    # The exact times are unknown. The last one is at the track's "last played" date
    # (when that falls inside the window); earlier ones are placed back to back before it.
    last = played
    step = max(int(t["duration"]) or 180, 60)
    rows = []
    for i in range(other):
        ts = max(lo + 1, last - (other - 1 - i) * step)
        rows.append((ts, local_iso(ts), t["title"], t["artist"], t["album"], t["duration"] or None,
                     t["duration"], None, "other", t["pid"], now))
    con.executemany(
        """INSERT INTO plays (ts, played_at, title, artist, album, duration, seconds_listened,
           skipped, source, persistent_id, ended_ts) VALUES (?,?,?,?,?,?,?,?,?,?,?)""", rows)
    return other, ignored


def run_snapshot(kind):
    con = db.connect()
    try:
        return snapshot(con, kind)
    finally:
        con.close()
