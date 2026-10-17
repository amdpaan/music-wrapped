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
                       seconds_listened REAL, skipped INTEGER, source TEXT, persistent_id TEXT, genre TEXT)""")
        con.execute("CREATE TABLE library (persistent_id TEXT, genre TEXT)")
        today = date(2026, 10, 14)
        noon = lambda d: int(datetime(d.year, d.month, d.day, 12).timestamp())
        for back in (1, 2, 3, 5):   # Tue, Mon, Sun, then a gap
            con.execute("INSERT INTO plays VALUES (?, 'A', 'X', '', 200, 60, 0, 'mac', 'P1', '')",
                        (noon(today - timedelta(days=back)),))
        con.execute("INSERT INTO plays VALUES (?, 'A', 'X', '', 200, NULL, NULL, 'other', 'P1', '')",
                    (noon(today - timedelta(days=1)),))
        # Nothing played today yet: the streak still counts up to yesterday.
        self.assertEqual(stats.streak_until(con, today), (3, date(2026, 10, 11), date(2026, 10, 13)))
        self.assertEqual(stats.streak_until(con, date(2026, 10, 9))[0], 1)
        plays = stats.plays_between(con, today - timedelta(days=7), today)
        self.assertAlmostEqual(stats.estimated_hours(plays) * 3600, 200)   # the iPhone play = full length
        row = stats.top_songs(plays, 1)[0]
        self.assertEqual((row.seconds, row.est), (440, 200))               # 4 x 60 s heard + 200 s estimated

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
