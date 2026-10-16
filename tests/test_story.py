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
            page = story.page(sl[1][1])
            self.assertIn('class="static"', page)          # animations off for PNGs
            self.assertIn("data-count", page)               # the minutes number

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
