"""YT Music history import (Google Takeout). No network: Apple's search is faked.

Run: python3 -m unittest tests.test_ytimport
"""

import json
import os
import tempfile
import unittest
import zipfile
from datetime import date, datetime, timezone
from pathlib import Path

os.environ.setdefault("MUSIC_WRAPPED_HOME", tempfile.mkdtemp())

from musicwrapped import db, library, stats, ytimport as Y  # noqa: E402

T0 = int(datetime(2026, 3, 2, 12, tzinfo=timezone.utc).timestamp())


def entry(title, artist, ts, header="YouTube Music", prefix="Watched "):
    e = {"header": header, "title": prefix + title, "titleUrl": "https://music.youtube.com/watch?v=x",
         "time": datetime.fromtimestamp(ts, timezone.utc).isoformat().replace("+00:00", "Z"), "products": ["YouTube"]}
    if artist is not None:
        e["subtitles"] = [{"name": artist, "url": "https://www.youtube.com/channel/x"}]
    return e


EXPORT = [
    entry("Glass Ocean", "Mira Sol - Topic", T0 + 200),
    entry("Glass Ocean", "Mira Sol - Topic", T0 + 100),
    entry("Paper Moons", "The Lanterns", T0 + 300),
    entry("A cooking video", "Some Channel", T0 + 400, header="YouTube"),   # not music
    entry("https://music.youtube.com/watch?v=gone", None, T0 + 500),          # removed song
]


class FakeApple(Y.Apple):
    """Answers from a tiny catalogue; counts requests."""
    SONGS = [{"wrapperType": "track", "trackName": "Glass Ocean (feat. Kai)", "artistName": "Mira Sol",
              "trackTimeMillis": 201000, "collectionName": "Tides", "primaryGenreName": "Pop", "artworkUrl100": None},
             {"wrapperType": "track", "trackName": "Glass Ocean", "artistName": "Other Band",
              "trackTimeMillis": 999000, "collectionName": "Wrong", "primaryGenreName": "Metal", "artworkUrl100": None}]

    def __init__(self, country):
        super().__init__(country)
        self.calls = 0

    def get(self, url):
        self.calls += 1
        if "entity=musicArtist" in url:
            return []
        return self.SONGS


class YTImport(unittest.TestCase):
    def setUp(self):
        for suffix in ("", "-wal", "-shm"):
            if os.path.exists(f"{db.paths.DB}{suffix}"):
                os.remove(f"{db.paths.DB}{suffix}")
        self.con = db.connect()

    def tearDown(self):
        self.con.close()

    def test_parse_keeps_only_yt_music_songs(self):
        plays = Y.parse(EXPORT)
        self.assertEqual(plays, [(T0 + 100, "Glass Ocean", "Mira Sol"), (T0 + 200, "Glass Ocean", "Mira Sol"),
                                 (T0 + 300, "Paper Moons", "The Lanterns")])

    def test_reads_watch_history_from_a_takeout_zip(self):
        with tempfile.TemporaryDirectory() as tmp:
            z = Path(tmp) / "takeout-20261027T000000Z-001.zip"
            with zipfile.ZipFile(z, "w") as f:
                f.writestr("Takeout/YouTube and YouTube Music/history/watch-history.json", json.dumps(EXPORT))
            self.assertEqual(len(Y.parse(Y.read_history(z))), 3)
            with self.assertRaises(SystemExit):
                Y.read_history(Path(tmp) / "watch-history.html")

    def test_match_is_this_song_by_this_artist_only(self):
        s = Y.match(FakeApple.SONGS, "Glass Ocean", "Mira Sol")
        self.assertEqual((s["duration"], s["album"], s["genre"]), (201, "Tides", "Pop"))
        self.assertIsNone(Y.match(FakeApple.SONGS, "Glass Ocean", "Nobody"))

    def test_import_stops_where_live_logging_starts_and_reimport_replaces(self):
        live = T0 + 250
        self.con.execute("""INSERT INTO plays (ts, played_at, title, artist, album, duration, seconds_listened, skipped,
                            source, persistent_id, ended_ts) VALUES (?,?,?,?,?,?,?,?,?,?,?)""",
                         (live, library.local_iso(live), "Paper Moons", "The Lanterns", "", 180, 180, 0, "yt",
                          Y.pid_for("Paper Moons", "The Lanterns"), live + 180))
        self.assertEqual(Y.cutoff(self.con), live)
        old = [p for p in Y.parse(EXPORT) if p[0] < Y.cutoff(self.con)]
        self.assertEqual(Y.import_plays(self.con, old, {}), 2)
        self.assertEqual(Y.import_plays(self.con, old, {}), 2)    # again: replaced, not added
        rows = self.con.execute("SELECT seconds_listened, duration, persistent_id FROM plays WHERE source = 'yt-history'").fetchall()
        self.assertEqual([tuple(r) for r in rows], [(Y.AVERAGE, None, Y.pid_for("Glass Ocean", "Mira Sol"))] * 2)

    def test_lookup_fills_rows_and_alltime_counts_history(self):
        plays = Y.parse(EXPORT)
        Y.import_plays(self.con, plays, {})
        apple = FakeApple("US")
        orig, Y.Apple = Y.Apple, lambda country: apple
        try:
            cache = {"songs": {}}
            songs = sorted({(t, a) for _, t, a in plays})
            Y.GAP, gap = 0, Y.GAP
            done, found = Y.look_up(self.con, songs, cache, log=lambda *_: None)
        finally:
            Y.Apple, Y.GAP = orig, gap
        self.assertEqual((done, found), (2, 1))                  # Paper Moons isn't in the fake catalogue
        self.assertIn(Y._key("Paper Moons", "The Lanterns"), cache["songs"])   # a miss is remembered too
        row = self.con.execute("""SELECT duration, seconds_listened, album, genre FROM plays
                                  WHERE source = 'yt-history' AND title = 'Glass Ocean' LIMIT 1""").fetchone()
        self.assertEqual(tuple(row), (201, 201, "Tides", "Pop"))
        top = stats.library_top(self.con, "songs", 5)
        self.assertEqual([(r.name, r.plays, r.seconds) for r in top],
                         [("Glass Ocean", 2, 402), ("Paper Moons", 1, Y.AVERAGE)])
        self.assertEqual([(r.name, r.plays) for r in stats.library_top(self.con, "genres", 5)], [("Pop", 2)])
        self.assertEqual(stats.library_totals(self.con)["yt_history"], 3)
        # In date reports the time is estimated (≈), like other-device plays.
        p = stats.plays_between(self.con, date(2026, 3, 1), date(2026, 3, 4))
        self.assertAlmostEqual(stats.estimated_hours(p), (402 + Y.AVERAGE) / 3600)


if __name__ == "__main__":
    unittest.main()
