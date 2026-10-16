"""Fake listening history so you can preview every report without waiting.

Uses its own folder (…/music-wrapped/demo/) and never touches your real plays.db.
Artists and songs are made up.
"""

import random
import time
from datetime import datetime, timedelta

from . import db, paths
from .library import local_iso

ARTISTS = {
    "Neon Harbor": ("Tidal Lights", ["Glass Ocean", "Paper Satellites", "Undertow", "Night Ferry"]),
    "Mira Sol": ("Golden Hour Club", ["Sundial", "Velvet Static", "Late Bloom", "Orchard"]),
    "The Quiet Engines": ("Low Gear", ["Signal Fire", "Overpass", "Northbound"]),
    "Kaito Rain": ("Monsoon Tapes", ["Petrichor", "Umbrella Song", "Grey Skies, Warm Hands"]),
    "Lumen & Ash": ("Ember", ["Smoke Signals", "Kindling", "Afterglow"]),
    "Saffron Youth": ("Spice Market", ["Turmeric", "Cardamom Dreams"]),
    "Polar Arcade": ("Pixel Winter", ["Snowcone", "Arcade Heart", "Level 9"]),
    "Dahlia Vex": ("Thorns", ["Bloom & Bite", "Hothouse"]),
    "Atlas Fields": ("Cartography", ["Contour Lines", "True North"]),
    "Juniper Static": ("Radio Garden", ["FM Lullaby", "Dial Tone"]),
}


def build():
    root = paths.SUPPORT / "demo"
    paths.SUPPORT = root
    paths.DB = root / "plays.db"
    paths.REPORTS = root / "reports"
    paths.SUMMARY = root / "summary.json"
    if paths.DB.exists():
        paths.DB.unlink()
    con = db.connect()
    rnd = random.Random(42)
    now = datetime.now()
    tracks = []
    for i, (artist, (album, songs)) in enumerate(ARTISTS.items()):
        for j, s in enumerate(songs):
            tracks.append({"pid": f"DEMO{i:02d}{j:02d}".ljust(16, "0"), "title": s, "artist": artist,
                           "album": album, "duration": rnd.randint(150, 290),
                           "weight": (len(ARTISTS) - i) ** 1.4 * rnd.uniform(0.5, 1.5)})
    # Two artists only appear later in the year (new discoveries).
    late = {"Polar Arcade": 70, "Juniper Static": 3}

    counts = {t["pid"]: 0 for t in tracks}
    rows = []
    start = datetime(now.year, 1, 1)
    day = start
    while day.date() <= now.date():
        if rnd.random() < 0.9:
            pool = [t for t in tracks if (now - day).days <= late.get(t["artist"], 10_000)]
            for _ in range(rnd.randint(3, 28)):
                hour = rnd.choices(range(24), weights=[1, 1, 0, 0, 0, 0, 1, 4, 6, 5, 4, 4, 5, 4, 4, 5, 6, 7, 6, 7, 9, 10, 8, 4])[0]
                ts_dt = day.replace(hour=hour, minute=rnd.randint(0, 59), second=rnd.randint(0, 59))
                if ts_dt > now:
                    continue
                t = rnd.choices(pool, weights=[x["weight"] for x in pool])[0]
                ts = int(ts_dt.timestamp())
                if rnd.random() < 0.7:
                    skipped = rnd.random() < 0.12
                    listened = rnd.randint(30, int(t["duration"] * 0.49)) if skipped else rnd.randint(int(t["duration"] * 0.9), t["duration"])
                    rows.append((ts, local_iso(ts), t["title"], t["artist"], t["album"], t["duration"], listened,
                                 int(skipped), "mac", t["pid"], ts + listened))
                    if not skipped:
                        counts[t["pid"]] += 1
                else:
                    rows.append((ts, local_iso(ts), t["title"], t["artist"], t["album"], t["duration"], t["duration"],
                                 None, "other", t["pid"], ts + t["duration"]))
                    counts[t["pid"]] += 1
        day += timedelta(days=1)

    with con:
        con.executemany("""INSERT INTO plays (ts, played_at, title, artist, album, duration, seconds_listened,
                           skipped, source, persistent_id, ended_ts) VALUES (?,?,?,?,?,?,?,?,?,?,?)""", rows)
        first = int(start.timestamp()) - 86400
        for t in tracks:
            base = 0 if t["artist"] in late else rnd.randint(0, 60)
            con.execute("""INSERT INTO library (persistent_id, title, artist, album, duration, play_count, played_ts,
                           added_ts, baseline_play_count, first_seen_ts, updated_ts) VALUES (?,?,?,?,?,?,?,?,?,?,?)""",
                        (t["pid"], t["title"], t["artist"], t["album"], t["duration"], base + counts[t["pid"]],
                         None, first if t["artist"] not in late else int((now - timedelta(days=late[t["artist"]])).timestamp()),
                         base, first, int(time.time())))
        con.execute("INSERT INTO snapshots (ts, kind, tracks, total_play_count, other_plays_added) VALUES (?,?,?,?,?)",
                    (first, "backfill", len(tracks), 0, 0))
    return con
