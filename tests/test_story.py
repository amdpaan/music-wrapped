"""Story slides build from the demo data for every period (rendering to PNG needs WebKit and isn't run here)."""

import argparse
import os
import tempfile
import unittest
from datetime import date


class StorySlides(unittest.TestCase):
    def test_slides_for_every_period(self):
        os.environ["MUSIC_WRAPPED_HOME"] = tempfile.mkdtemp()
        from musicwrapped import demo, paths, story
        paths.SUPPORT = paths.Path(os.environ["MUSIC_WRAPPED_HOME"])
        con = demo.build()
        a = argparse.Namespace(week=None, month=None, current=True, year=None)
        for kind in ("weekly", "monthly", "yearly", "alltime"):
            name, sl = story.slides_for(con, kind, a, today=date.today())
            names = [n for n, _ in sl]
            self.assertEqual(names[:5], ["intro", "minutes", "top-song", "top-artist", "top-songs"], kind)
            self.assertEqual(names[-1], "summary", kind)
            if kind in ("weekly", "monthly"):
                self.assertIn("changes", names, kind)    # compared with the period before
            page = story.page(sl[1][1])
            self.assertIn('class="static"', page)          # animations off for PNGs
            self.assertIn("data-count", page)               # the minutes number

    def test_streak_and_estimates(self):
        import sqlite3
        from datetime import datetime, timedelta
        from musicwrapped import stats
        con = sqlite3.connect(":memory:")
        con.row_factory = sqlite3.Row
        con.execute("""CREATE TABLE plays (ts INTEGER, title TEXT, artist TEXT, album TEXT, duration REAL,
                       seconds_listened REAL, skipped INTEGER, source TEXT, persistent_id TEXT, genre TEXT,
                       ended_ts INTEGER)""")
        con.execute("CREATE TABLE library (persistent_id TEXT, genre TEXT)")
        today = date(2026, 10, 14)
        noon = lambda d: int(datetime(d.year, d.month, d.day, 12).timestamp())
        for back in (1, 2, 3, 5):   # Tue, Mon, Sun, then a gap
            con.execute("INSERT INTO plays VALUES (?, 'A', 'X', '', 200, 60, 0, 'mac', 'P1', '', NULL)",
                        (noon(today - timedelta(days=back)),))
        con.execute("INSERT INTO plays VALUES (?, 'A', 'X', '', 200, NULL, NULL, 'other', 'P1', '', NULL)",
                    (noon(today - timedelta(days=1)),))
        # Nothing played today yet: the streak still counts up to yesterday.
        self.assertEqual(stats.streak_until(con, today), (3, date(2026, 10, 11), date(2026, 10, 13)))
        self.assertEqual(stats.streak_until(con, date(2026, 10, 9))[0], 1)
        plays = stats.plays_between(con, today - timedelta(days=7), today)
        self.assertAlmostEqual(stats.estimated_hours(plays) * 3600, 200)   # the iPhone play = full length
        row = stats.top_songs(plays, 1)[0]
        self.assertEqual((row.seconds, row.est), (440, 200))               # 4 x 60 s heard + 200 s estimated

    def test_genre_spellings_merge(self):
        from musicwrapped import stats
        self.assertEqual({stats.genre_name(g) for g in ("Hip-Hop/Rap", "Hip Hop", "hip-hop", "Rap")}, {"Hip-Hop/Rap"})
        self.assertEqual({stats.genre_name(g) for g in ("R&B/Soul", "RnB", "R&B")}, {"R&B/Soul"})
        self.assertEqual(stats.genre_name("K Pop"), "K-Pop")
        # Unknown genres merge by spelling under the first one seen, and stay apart from other genres.
        self.assertEqual(stats.genre_name("Math Rock"), "Math Rock")
        self.assertEqual(stats.genre_name("math-rock"), "Math Rock")
        self.assertNotEqual(stats.genre_name("Rock"), stats.genre_name("Pop"))
        self.assertEqual(stats.genre_name("  "), "")

    def test_session_and_replays(self):
        from datetime import datetime
        from musicwrapped import stats
        def play(h, m, secs=200, source="mac", title="A"):
            t = int(datetime(2026, 10, 14, h, m).timestamp())
            return stats.Play(t, datetime.fromtimestamp(t), title, "X", "", 200, secs, 0, source, "P" + title, "", t + secs)
        plays = [play(9, 0), play(9, 5), play(9, 18),          # 9:18 starts 9.7 min after 9:08:20 -> same session
                 play(12, 0), play(12, 4),                       # a shorter one
                 play(20, 0, source="other", title="B")]         # other devices never make a session
        start, end, n = stats.longest_session(plays)
        self.assertEqual((start.hour, start.minute, end.hour, end.minute, n), (9, 0, 9, 21, 3))
        r, day = stats.most_replayed_day(plays)
        self.assertEqual((r.name, r.plays, day.day), ("A", 5, 14))
        self.assertIsNone(stats.most_replayed_day(plays[:2]))   # fewer than 3 plays isn't a record

    def test_every_full_report_builds(self):
        # The slides test above only builds slides; this builds each whole page (a custom report once
        # crashed here while every slide test passed).
        from datetime import timedelta
        from musicwrapped import demo, paths, reports
        os.environ["MUSIC_WRAPPED_HOME"] = tempfile.mkdtemp()
        paths.SUPPORT = paths.Path(os.environ["MUSIC_WRAPPED_HOME"])
        con = demo.build()
        today = date.today()
        for kind, name, html in (reports.weekly(con, today), reports.monthly(con, today.year, today.month, so_far=True),
                                 reports.yearly(con, today.year), reports.alltime(con),
                                 reports.custom(con, today - timedelta(days=60), today, "Test range")):
            self.assertIn("</html>", html, kind)
            self.assertIn('id="details"', html, kind)

    def test_big_numbers_fit_their_column(self):
        from musicwrapped import slides
        html = slides._num(1234567, 30, 340)
        self.assertIn("cqw", html)
        self.assertIn('data-count="1234567"', html)

    def test_css_braces_balance(self):
        # An unclosed block once hid every cover in the story images (rules after it only applied
        # on wide screens), so check that braces never go negative and close at the end.
        from musicwrapped import render, slides, story
        for name, css in (("render", render.CSS), ("slides", slides.CSS), ("story", story.BASE_CSS)):
            depth = 0
            for ch in css:
                depth += (ch == "{") - (ch == "}")
                self.assertGreaterEqual(depth, 0, name)
            self.assertEqual(depth, 0, name)


if __name__ == "__main__":
    unittest.main()
