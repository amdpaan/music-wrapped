"""Story cards build from the demo data (rendering to PNG needs WebKit and isn't run here)."""

import argparse
import os
import tempfile
import unittest
from datetime import date


class StoryCards(unittest.TestCase):
    def test_cards_for_every_period(self):
        os.environ["MUSIC_WRAPPED_HOME"] = tempfile.mkdtemp()
        from musicwrapped import demo, paths, story
        paths.SUPPORT = paths.Path(os.environ["MUSIC_WRAPPED_HOME"])
        con = demo.build()
        a = argparse.Namespace(week=None, month=None, current=True, year=None)
        for kind in ("weekly", "monthly", "yearly", "alltime"):
            name, label, words, start, end = story.period(kind, a, today=date.today())
            d = story.collect(con, kind, start, end)
            self.assertIsNotNone(d, kind)
            pages = story.cards(d, label, words, "foot")
            self.assertEqual([p[0] for p in pages], ["01-intro", "02-top-song", "03-top-artist",
                                                      "04-top-songs", "05-top-genre", "06-summary"])
            self.assertIn(f"{d['minutes']:,}", pages[0][1])

    def test_big_numbers_fit(self):
        from musicwrapped import story
        self.assertLessEqual(story._huge("1,234,567") * 9 * 0.62, 808)
        self.assertEqual(story._huge("42"), 300)


if __name__ == "__main__":
    unittest.main()
