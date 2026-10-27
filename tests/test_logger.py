"""End-to-end tests for the Swift logger: builds it, runs it against a scratch data folder and
sends it fake Music events on a private notification name (so the real logger never sees them).

Takes about 30 s (it compiles the logger). Skip with MUSIC_WRAPPED_SKIP_LOGGER_TESTS=1.
Run: python3 -m unittest tests.test_logger -v
"""

import json
import os
import shutil
import signal
import sqlite3
import subprocess
import tempfile
import time
import unittest
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
SKIP = os.environ.get("MUSIC_WRAPPED_SKIP_LOGGER_TESTS") or not shutil.which("swiftc")

A, B = 41, 42                      # persistent IDs; the logger shows them as 16-digit hex
HEX = {A: "0000000000000029", B: "000000000000002A"}


@unittest.skipIf(SKIP, "swiftc not found or MUSIC_WRAPPED_SKIP_LOGGER_TESTS set")
class LoggerTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.build = tempfile.mkdtemp()
        cls.exe = str(Path(cls.build) / "music-wrapped-logger")
        subprocess.run(["swiftc", "-o", cls.exe, str(REPO / "logger/main.swift")], check=True)
        cls.channel = f"com.musicwrapped.test.{os.getpid()}"

    @classmethod
    def tearDownClass(cls):
        shutil.rmtree(cls.build, ignore_errors=True)

    def setUp(self):
        self.home = tempfile.mkdtemp()
        self.proc = None

    def tearDown(self):
        self.stop()
        shutil.rmtree(self.home, ignore_errors=True)

    # ---------- helpers ----------

    def env(self, query=None):
        e = dict(os.environ, MUSIC_WRAPPED_HOME=self.home, MUSIC_WRAPPED_NOTIFICATION=self.channel,
                 MUSIC_WRAPPED_MIN_SECONDS="2", MUSIC_WRAPPED_TEST_QUERY=json.dumps(query) if query else "none")
        if getattr(self, "np_feed", None):
            e["MUSIC_WRAPPED_NOWPLAYING_CMD"] = str(self.np_script)
        return e

    def start(self, query=None):
        self.log = open(Path(self.home) / "logger.log", "a+")
        self.proc = subprocess.Popen([self.exe], env=self.env(query), stderr=self.log)
        for _ in range(100):  # wait until it's listening
            if "starting in" in (Path(self.home) / "logger.log").read_text():
                break
            time.sleep(0.05)
        time.sleep(0.4)

    def stop(self):
        if self.proc and self.proc.poll() is None:
            self.proc.send_signal(signal.SIGTERM)
            self.proc.wait(timeout=5)
        self.proc = None
        if getattr(self, "log", None):
            self.log.close()
            self.log = None

    def post(self, state, pid=A, seconds=8, genre="Pop"):
        info = {"Player State": state}
        if state != "Stopped":
            info.update({"PersistentID": pid, "Name": f"Song {pid}", "Artist": "Test Artist",
                         "Album": "Test Album", "Total Time": seconds * 1000, "Genre": genre})
        subprocess.run([self.exe, "--post", json.dumps(info)], env=self.env(), check=True)
        time.sleep(0.15)  # let the logger handle it

    def rows(self):
        db = Path(self.home) / "plays.db"
        if not db.exists():
            return []
        con = sqlite3.connect(str(db))
        con.row_factory = sqlite3.Row
        out = [dict(r) for r in con.execute("SELECT * FROM plays ORDER BY id")]
        con.close()
        return out

    # ---------- tests ----------

    def test_counts_after_minimum_and_marks_skips(self):
        self.start()
        self.post("Playing", A)
        time.sleep(3)
        self.post("Playing", B)          # track change ends A (3 s of 8 s: skipped)
        time.sleep(0.5)
        self.post("Stopped")             # B: 0.5 s, below the minimum
        rows = self.rows()
        self.assertEqual(len(rows), 1)
        r = rows[0]
        self.assertEqual((r["title"], r["persistent_id"], r["source"], r["skipped"], r["genre"]),
                         (f"Song {A}", HEX[A], "mac", 1, "Pop"))
        self.assertAlmostEqual(r["seconds_listened"], 3, delta=1)
        summary = json.loads((Path(self.home) / "summary.json").read_text())
        self.assertEqual(summary["top_genre"], {"name": "Pop", "plays": 1})
        self.assertEqual(summary["top_song"]["pid"], HEX[A])
        self.assertEqual(len(summary["daily_minutes"]), 7)
        self.assertGreater(sum(summary["daily_minutes"]), 0)
        self.assertTrue((Path(self.home) / "heartbeat.json").exists())

    def test_pauses_excluded_and_duplicates_dont_split(self):
        # Each post launches a process, which can take a second on a slow machine (CI), so the check
        # is relative to the measured wall-clock time rather than an exact number: the 4 s pause
        # must be missing from it, and the ~3.5 s of playing must be there.
        self.start()
        t0 = time.time()
        self.post("Playing", A, seconds=20)
        time.sleep(1.5)
        self.post("Paused", A, seconds=20)
        time.sleep(4)                    # paused time must not count
        self.post("Playing", A, seconds=20)
        time.sleep(1)
        self.post("Playing", A, seconds=20)  # duplicate event Music sometimes sends
        time.sleep(1)
        self.post("Stopped")
        wall = time.time() - t0
        rows = self.rows()
        self.assertEqual(len(rows), 1)
        listened = rows[0]["seconds_listened"]
        self.assertGreaterEqual(listened, 2.5)
        self.assertLessEqual(listened, wall - 3, f"pause counted? listened {listened:.1f} s of {wall:.1f} s")

    def test_repeat_of_same_track_is_two_plays(self):
        self.start()
        self.post("Playing", A, seconds=3)
        time.sleep(3)                    # >= 90 % of the track
        self.post("Playing", A, seconds=3)   # starts again
        time.sleep(2.5)
        self.post("Stopped")
        rows = self.rows()
        self.assertEqual(len(rows), 2)
        self.assertEqual(rows[0]["skipped"], 0)

    def test_restart_resumes_same_song_without_double_count(self):
        self.start()
        self.post("Playing", A, seconds=30)
        time.sleep(1)                    # under the 2 s test minimum: not counted yet
        self.stop()                      # launchd stop: saved, not logged
        self.assertEqual(self.rows(), [])
        self.assertTrue((Path(self.home) / "pending.json").exists())
        (Path(self.home) / "heartbeat.json").unlink()
        self.start(query={"Player State": "Playing", "PersistentID": HEX[A], "Name": f"Song {A}",
                          "Artist": "Test Artist", "Album": "Test Album", "Total Time": 30000.0})
        self.assertFalse((Path(self.home) / "pending.json").exists())
        self.assertTrue((Path(self.home) / "heartbeat.json").exists())  # already playing at startup
        time.sleep(1.5)
        self.post("Stopped")
        rows = self.rows()
        self.assertEqual(len(rows), 1)   # one play, not two
        self.assertAlmostEqual(rows[0]["seconds_listened"], 2.5, delta=1)

    def test_counted_at_the_minimum_then_finished_on_the_same_row(self):
        # Reports update as soon as a song counts, not when it ends.
        self.start()
        self.post("Playing", A, seconds=20)
        time.sleep(3)                    # past the 2 s test minimum, still playing
        rows = self.rows()
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["skipped"], 0)            # not a skip (yet)
        self.assertTrue((Path(self.home) / "summary.json").exists())
        early_id = rows[0]["id"]
        time.sleep(1.5)
        self.post("Stopped")
        rows = self.rows()
        self.assertEqual([r["id"] for r in rows], [early_id])   # the same row, finished
        self.assertGreater(rows[0]["seconds_listened"], 3)
        self.assertEqual(rows[0]["skipped"], 1)            # stopped well before half of 20 s
        self.assertGreater(rows[0]["ended_ts"], rows[0]["ts"] + 3)

    def test_restart_after_counting_keeps_one_row(self):
        self.start()
        self.post("Playing", A, seconds=30)
        time.sleep(3)                    # counted
        self.assertEqual(len(self.rows()), 1)
        self.stop()                      # saved with its row id
        self.start(query={"Player State": "Playing", "PersistentID": HEX[A], "Name": f"Song {A}",
                          "Artist": "Test Artist", "Album": "Test Album", "Total Time": 30000.0})
        time.sleep(1)
        self.post("Stopped")
        rows = self.rows()
        self.assertEqual(len(rows), 1)   # resumed into the same row
        self.assertGreater(rows[0]["seconds_listened"], 3)

    def test_restart_with_another_song_logs_the_saved_one(self):
        self.start()
        self.post("Playing", A, seconds=30)
        time.sleep(2.5)
        self.stop()
        self.start(query={"Player State": "Playing", "PersistentID": HEX[B], "Name": f"Song {B}",
                          "Artist": "Test Artist", "Album": "Test Album", "Total Time": 30000.0})
        rows = self.rows()
        self.assertEqual([r["persistent_id"] for r in rows], [HEX[A]])
        self.assertAlmostEqual(rows[0]["seconds_listened"], 2.5, delta=1)

    # ---------- other apps (Now Playing helper, faked) ----------

    def now_playing(self):
        """Use a fake Now Playing helper: a script that prints whatever np() appends to a file."""
        self.np_feed = Path(self.home) / "np.txt"
        self.np_feed.write_text("")
        self.np_script = Path(self.home) / "fake-nowplaying.sh"
        self.np_script.write_text(f'#!/bin/sh\nexec tail -n +1 -f "{self.np_feed}"\n')
        self.np_script.chmod(0o755)

    def np(self, state, title="YT Song", elapsed=0.0, duration=30.0, **extra):
        line = {"state": state}
        if state != "Stopped":
            line.update(title=title, artist="YT Artist", album="YT Album", duration=duration, elapsed=elapsed)
            line.update(extra)
        with open(self.np_feed, "a") as f:
            f.write(json.dumps(line) + "\n")
        time.sleep(0.4)  # tail -f polls

    def test_other_app_plays_are_logged_as_yt_with_cover(self):
        self.now_playing()
        self.start()
        png = ("iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mNk+M9QDwADhgGAWjR9awAAAABJRU5ErkJggg==")
        self.np("Playing", art=png)
        self.post("Playing", A, seconds=30)   # the Music app at the same time stays separate
        time.sleep(3)
        self.np("Paused", elapsed=3)
        self.post("Stopped")
        rows = self.rows()
        self.assertEqual(sorted(r["source"] for r in rows), ["mac", "yt"])
        yt = next(r for r in rows if r["source"] == "yt")
        self.assertEqual((yt["title"], yt["artist"], yt["album"], yt["duration"]), ("YT Song", "YT Artist", "YT Album", 30))
        self.assertRegex(yt["persistent_id"], r"^YT[0-9A-F]{14}$")
        for d in ("artwork", "artwork/640"):
            self.assertTrue((Path(self.home) / d / f"{yt['persistent_id']}.jpg").exists(), d)
        self.assertEqual(json.loads((Path(self.home) / "summary.json").read_text())["plays"], 2)

    def test_other_app_skip_repeat_and_seek(self):
        self.now_playing()
        self.start()
        # The helper only reports changes, so a repeat shows up as a position far behind where the
        # song should be by now.
        self.np("Playing", "One", elapsed=30, duration=60)
        time.sleep(2.5)                                         # counted
        self.np("Playing", "One", elapsed=0.5, duration=60)    # repeat: back to the start → a new play
        time.sleep(2.5)                                         # counted
        self.np("Playing", "One", elapsed=40, duration=60)     # seek forward
        self.np("Playing", "One", elapsed=20, duration=60)     # seek back, not to the start: same play
        self.np("Playing", "Two", duration=60)                 # skip to another song
        time.sleep(0.5)
        self.np("Stopped")
        rows = self.rows()
        self.assertEqual([r["title"] for r in rows], ["One", "One"])
        self.assertEqual([r["skipped"] for r in rows], [1, 1])

    def test_other_app_length_and_album_arriving_late_are_kept(self):
        # YT Music sends the title first, then the length and album a moment later.
        self.now_playing()
        self.start()
        self.np("Playing", "Late", duration=0, album="")
        self.np("Playing", "Late", duration=60, elapsed=0.4, album="Late Album")
        time.sleep(3)                     # counted (2.5 s of 60: a skip)
        self.np("Stopped")
        rows = self.rows()
        self.assertEqual(len(rows), 1)
        self.assertEqual((rows[0]["duration"], rows[0]["album"], rows[0]["skipped"]), (60, "Late Album", 1))

    def test_other_app_restart_resumes_the_same_song(self):
        self.now_playing()
        self.start()
        self.np("Playing", duration=60)
        time.sleep(3)                     # counted
        self.stop()                       # saved to pending-yt.json
        self.assertTrue((Path(self.home) / "pending-yt.json").exists())
        self.start()                      # the fake helper replays the feed; its last line is still playing
        time.sleep(1)
        self.np("Stopped")
        rows = self.rows()
        self.assertEqual(len(rows), 1)
        self.assertGreater(rows[0]["seconds_listened"], 3)


if __name__ == "__main__":
    unittest.main()
