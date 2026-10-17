"""music-wrapped serve only hands out report pages under the secret link."""

import tempfile
import threading
import unittest
import urllib.error
import urllib.request
from functools import partial
from http.server import ThreadingHTTPServer
from pathlib import Path


class _NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, *a, **k):
        return None


class Serve(unittest.TestCase):
    def setUp(self):
        from musicwrapped import paths, serve
        self.root = Path(tempfile.mkdtemp())
        reports = self.root / "reports"
        (self.root / "stories/weekly/2026-W42").mkdir(parents=True)
        (self.root / "stories/weekly/2026-W42/index.html").write_text("stories")
        (reports / "weekly").mkdir(parents=True)
        (reports / "index.html").write_text("home")
        (reports / "weekly/latest.html").write_text("week")
        (self.root / "plays.db").write_text("secret")
        self._old = paths.REPORTS, paths.SUPPORT
        paths.REPORTS, paths.SUPPORT = reports, self.root
        (reports / "weekly/2026-W42.html").write_text("week")
        import os, time
        old = time.time() - 60   # the report is older than its story images: no re-render
        os.utime(reports / "weekly/2026-W42.html", (old, old))
        h = partial(type("H", (serve.Handler,), {"code": "abc123"}), directory=str(self.root))
        self.server = ThreadingHTTPServer(("127.0.0.1", 0), h)
        threading.Thread(target=self.server.serve_forever, daemon=True).start()
        self.base = f"http://127.0.0.1:{self.server.server_port}"
        self.opener = urllib.request.build_opener(_NoRedirect)

    def tearDown(self):
        from musicwrapped import paths
        self.server.shutdown()
        self.server.server_close()
        paths.REPORTS, paths.SUPPORT = self._old

    def get(self, path):
        try:
            with self.opener.open(self.base + path) as r:
                return r.status, r.read().decode()
        except urllib.error.HTTPError as ex:
            return ex.code, ""

    def test_access(self):
        self.assertEqual(self.get("/abc123/")[0], 302)                     # -> /abc123/reports/
        self.assertEqual(self.get("/abc123/reports/"), (200, "home"))
        self.assertEqual(self.get("/abc123/reports/weekly/latest.html"), (200, "week"))
        self.assertEqual(self.get("/abc123/stories/weekly/2026-W42/"), (200, "stories"))
        self.assertEqual(self.get("/abc123")[0], 302)
        self.assertEqual(self.get("/abc123/reports/weekly")[0], 301)
        for path in ("/", "/reports/weekly/latest.html", "/abc12/", "/abc1234/", "/abc123x/reports/index.html",
                     "/abc123/reports/weekly/", "/abc123/plays.db", "/abc123/reports/../plays.db",
                     "/abc123/%2e%2e/plays.db", "/abc123/reports/%2e%2e/plays.db", "/abc123/config.json",
                     "/abc123/stories/weekly/2026-W01/", "/abc123/stories/custom/x/", "/abc123/backups/"):
            self.assertEqual(self.get(path)[0], 404, path)


if __name__ == "__main__":
    unittest.main()
