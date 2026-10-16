"""Counting rules: snapshots must never double count plays the Mac logger already logged.

Run: python3 -m unittest discover tests
"""

import os
import tempfile
import unittest
from datetime import date, datetime

os.environ["MUSIC_WRAPPED_HOME"] = tempfile.mkdtemp()

from musicwrapped import db, library, reports, stats  # noqa: E402

T0 = int(datetime(2026, 10, 5, 12).timestamp())  # Monday


def track(pid, plays, played_ts=None, added_ts=T0 - 86400 * 30, title="Song", artist="Artist"):
    return {"pid": pid, "title": title, "artist": artist, "album": "Album", "duration": 200.0,
            "plays": plays, "played_ts": played_ts, "added_ts": added_ts}


def mac_play(con, pid, ts, listened, title="Song", artist="Artist"):
    con.execute("""INSERT INTO plays (ts, played_at, title, artist, album, duration, seconds_listened, skipped,
                   source, persistent_id, ended_ts) VALUES (?,?,?,?,?,?,?,?,?,?,?)""",
                (ts, library.local_iso(ts), title, artist, "Album", 200.0, listened, int(listened < 100),
                 "mac", pid, ts + listened))
    con.commit()


class Counting(unittest.TestCase):
    def setUp(self):
        for suffix in ("", "-wal", "-shm"):
            if os.path.exists(f"{db.paths.DB}{suffix}"):
                os.remove(f"{db.paths.DB}{suffix}")
        self.con = db.connect()

    def tearDown(self):
        self.con.close()

    def count(self, source):
        return self.con.execute("SELECT COUNT(*) FROM plays WHERE source=?", (source,)).fetchone()[0]

    def test_backfill_adds_no_plays(self):
        r = library.snapshot(self.con, tracks=[track("A", 10)], now=T0)
        self.assertEqual(r["kind"], "backfill")
        self.assertEqual(self.count("other"), 0)
        self.assertEqual(stats.library_totals(self.con)["plays"], 10)

    def test_mac_plays_are_not_counted_again(self):
        library.snapshot(self.con, tracks=[track("A", 10)], now=T0)
        mac_play(self.con, "A", T0 + 100, 200)   # finished -> Music counted it
        mac_play(self.con, "A", T0 + 400, 195)   # finished
        mac_play(self.con, "A", T0 + 700, 60)    # skipped -> Music didn't count it
        # Library went 10 -> 15: 2 from the Mac, so 3 came from another device.
        r = library.snapshot(self.con, tracks=[track("A", 15, played_ts=T0 + 3000)], now=T0 + 3600)
        self.assertEqual(r["other_plays"], 3)
        self.assertEqual(self.count("mac"), 3)
        self.assertEqual(self.count("other"), 3)
        # Taking another snapshot with no change adds nothing.
        r = library.snapshot(self.con, tracks=[track("A", 15, played_ts=T0 + 3000)], now=T0 + 7200)
        self.assertEqual(r["other_plays"], 0)

    def test_new_track_is_baseline_only(self):
        library.snapshot(self.con, tracks=[track("A", 1)], now=T0)
        mac_play(self.con, "B", T0 + 100, 200)  # logged on the Mac before B was ever snapshotted
        r = library.snapshot(self.con, tracks=[track("A", 1), track("B", 4, added_ts=T0 + 50, played_ts=T0 + 900)],
                             now=T0 + 3600)
        self.assertEqual(r["other_plays"], 0)
        self.assertEqual(self.count("mac"), 1)  # the Mac play still counts
        # Only increases after the baseline are counted.
        r = library.snapshot(self.con, tracks=[track("A", 1), track("B", 6, played_ts=T0 + 5000)], now=T0 + 7200)
        self.assertEqual(r["other_plays"], 2)

    def test_date_ranges_add_up(self):
        library.snapshot(self.con, tracks=[track("A", 0)], now=T0 - 10)
        week1 = int(datetime(2026, 10, 6, 9).timestamp())
        week2 = int(datetime(2026, 10, 14, 9).timestamp())
        for i in range(3):
            mac_play(self.con, "A", week1 + i * 300, 200)
        for i in range(5):
            mac_play(self.con, "A", week2 + i * 300, 200)
        w1 = stats.plays_between(self.con, *reports.week_of(date(2026, 10, 6)))
        w2 = stats.plays_between(self.con, *reports.week_of(date(2026, 10, 14)))
        month = stats.plays_between(self.con, *reports.month_bounds(2026, 10))
        self.assertEqual((len(w1), len(w2), len(month)), (3, 5, 8))

    def test_new_artists(self):
        library.snapshot(self.con, tracks=[track("A", 9, artist="Old")], now=T0)  # backfill
        later = T0 + 86400 * 3
        library.snapshot(self.con, tracks=[track("A", 9, artist="Old"), track("B", 2, artist="Fresh", added_ts=later - 100)],
                         now=later)
        mac_play(self.con, "A", later + 100, 200, artist="Old")
        mac_play(self.con, "B", later + 400, 200, artist="Fresh")
        plays = stats.plays_between(self.con, date(2026, 10, 6), date(2026, 10, 13))
        self.assertEqual([r.name for r in stats.new_artists(self.con, plays, date(2026, 10, 6))], ["Fresh"])
        # In a later period, Fresh's baseline plays (first seen before it) make it known.
        self.assertEqual(stats.new_artists(self.con, plays, date(2026, 10, 12)), [])


if __name__ == "__main__":
    unittest.main()
