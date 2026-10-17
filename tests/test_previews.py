"""Song previews: matching never picks a different song, and slides get them only when turned on."""

import json
import os
import tempfile
import unittest
from pathlib import Path


class Previews(unittest.TestCase):
    def setUp(self):
        from musicwrapped import paths
        self.home = Path(tempfile.mkdtemp())
        self._old = paths.SUPPORT, paths.CONFIG
        paths.SUPPORT, paths.CONFIG = self.home, self.home / "config.json"

    def tearDown(self):
        from musicwrapped import paths
        paths.SUPPORT, paths.CONFIG = self._old

    def test_match_is_strict(self):
        from musicwrapped.previews import best_match
        res = [{"trackName": "Glass Ocean (Live)", "artistName": "Neon Harbor", "previewUrl": "live"},
               {"trackName": "Glass Ocean", "artistName": "Someone Else", "previewUrl": "cover"},
               {"trackName": "Glass Ocean - Single Version", "artistName": "Neon Harbor & Mira Sol", "previewUrl": "ok"}]
        # "(Live)" and "- Single Version" are ignored when comparing titles; the first exact one wins.
        self.assertEqual(best_match(res, "Glass Ocean", "Neon Harbor"), "live")
        self.assertEqual(best_match(res[1:], "Glass Ocean", "Neon Harbor"), "ok")
        self.assertIsNone(best_match(res[1:2], "Glass Ocean", "Neon Harbor"))     # a cover by someone else
        self.assertIsNone(best_match(res, "Paper Satellites", "Neon Harbor"))     # never another song
        self.assertIsNone(best_match([{"trackName": "Glass Ocean", "artistName": "Neon Harbor"}], "Glass Ocean", "Neon Harbor"))

    def test_off_by_default_and_attached_when_on(self):
        from musicwrapped import previews, slides
        from musicwrapped.stats import Row
        d = {"songs": [Row("Glass Ocean", "Neon Harbor", 3, 600), Row("Sundial", "Mira Sol", 2, 400)],
             "artist_song": ("Glass Ocean", "Neon Harbor")}
        parts = [("intro", '<section class="slide x">a</section>'), ("top-songs", '<section class="slide y">b</section>'),
                 ("records", '<section class="slide z">c</section>')]
        self.assertFalse(previews.enabled())
        self.assertEqual(slides.soundtrack(parts, d), parts)                      # off: untouched, no lookups
        previews.set_enabled(True)
        old = previews.lookup
        previews.lookup = lambda t, a, cache=None, country=None: f"https://example.com/{t.replace(' ', '')}.m4a"
        try:
            out = dict(slides.soundtrack(parts, d))
        finally:
            previews.lookup = old
        self.assertIn('data-preview="https://example.com/GlassOcean.m4a"', out["intro"])
        self.assertIn('data-preview="https://example.com/Sundial.m4a"', out["top-songs"])
        self.assertNotIn("data-preview", out["records"])                          # keeps the song playing
        self.assertTrue(json.loads((self.home / "config.json").read_text())["previews"])

    def test_cache_skips_the_network(self):
        import time
        from musicwrapped import previews
        cache = {"MY|Glass Ocean|Neon Harbor": {"url": "cached", "ts": int(time.time())},
                 "MY|Nope|Nobody": {"url": None, "ts": int(time.time())}}
        old = previews.urllib.request.urlopen
        previews.urllib.request.urlopen = lambda *a, **k: self.fail("no request expected")
        try:
            self.assertEqual(previews.lookup("Glass Ocean", "Neon Harbor", cache, "MY"), "cached")
            self.assertIsNone(previews.lookup("Nope", "Nobody", cache, "MY"))    # a recent miss isn't retried
        finally:
            previews.urllib.request.urlopen = old


if __name__ == "__main__":
    unittest.main()
