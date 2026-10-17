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
        (reports / "weekly").mkdir(parents=True)
        (reports / "index.html").write_text("home")
        (reports / "weekly/latest.html").write_text("week")
        (self.root / "plays.db").write_text("secret")
        self._old = paths.REPORTS
        paths.REPORTS = reports
        h = partial(type("H", (serve.Handler,), {"code": "abc123"}), directory=str(reports))
        self.server = ThreadingHTTPServer(("127.0.0.1", 0), h)
        threading.Thread(target=self.server.serve_forever, daemon=True).start()
        self.base = f"http://127.0.0.1:{self.server.server_port}"
        self.opener = urllib.request.build_opener(_NoRedirect)

    def tearDown(self):
        from musicwrapped import paths
        self.server.shutdown()
        self.server.server_close()
        paths.REPORTS = self._old

    def get(self, path):
        try:
            with self.opener.open(self.base + path) as r:
                return r.status, r.read().decode()
        except urllib.error.HTTPError as ex:
            return ex.code, ""

    def test_access(self):
        self.assertEqual(self.get("/abc123/"), (200, "home"))
        self.assertEqual(self.get("/abc123/weekly/latest.html"), (200, "week"))
        self.assertEqual(self.get("/abc123")[0], 301)
        self.assertEqual(self.get("/abc123/weekly")[0], 301)
        for path in ("/", "/weekly/latest.html", "/abc12/", "/abc1234/", "/abc123x/weekly/latest.html",
                     "/abc123/weekly/", "/abc123/../plays.db", "/abc123/%2e%2e/plays.db"):
            self.assertEqual(self.get(path)[0], 404, path)


if __name__ == "__main__":
    unittest.main()
