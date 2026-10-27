"""Imports your YT Music history from a Google Takeout export (`music-wrapped import-yt`).

Takeout's `watch-history.json` lists every song YT Music played on any device (Mac, iPhone, …) with
its time, title and artist, but not its length. Rows get `source = 'yt-history'` and the same ids as
plays logged live from YT Music (`syntheticPID` in logger/main.swift), so covers and all-time entries
are shared. Only history from before live logging started is imported, so nothing counts twice.
Re-importing a newer export replaces the earlier import.

Song lengths, albums, genres and covers come from Apple's public iTunes Search API (title and artist
only), with the same exact-match rule as song previews: never a different song. Lookups are slow on
purpose (Apple allows about 20 a minute), cached in `songinfo.json`, and safe to stop and resume;
songs not found count as AVERAGE seconds. Imported time is marked as estimated (≈) in reports.
"""

import io
import json
import re
import subprocess
import tempfile
import time
import urllib.error
import urllib.parse
import urllib.request
import zipfile
from datetime import datetime
from pathlib import Path

from . import library, paths, previews

SOURCE = "yt-history"
AVERAGE = 210            # seconds per play for songs Apple doesn't know
CACHE = "songinfo.json"
GAP = 3.2                # seconds between requests to Apple (about 19 a minute)
TITLE_PREFIXES = ("Watched ", "Menonton ", "Ditonton ")   # Takeout's verb, by account language


def pid_for(title, artist):
    """Same id as the logger gives a song from another app: "YT" + 14 hex digits of
    FNV-1a(lowercased title, unit separator, lowercased artist)."""
    h = 0xcbf29ce484222325
    for b in f"{title.lower()}\x1f{artist.lower()}".encode("utf-8"):
        h ^= b
        h = (h * 0x100000001b3) & 0xFFFFFFFFFFFFFFFF
    return "YT%014X" % (h & 0x00FFFFFFFFFFFFFF)


# ---------- reading the export ----------

def find_export(given=None):
    """The export to read: the given zip / json / folder, else the newest Takeout zip or folder in
    ~/Downloads. None if there isn't one."""
    if given:
        return Path(given).expanduser()
    downloads = Path.home() / "Downloads"
    found = [p for p in downloads.glob("takeout-*.zip")] + [p for p in downloads.glob("Takeout*") if p.is_dir()]
    return max(found, key=lambda p: p.stat().st_mtime) if found else None


def read_history(path):
    """The parsed watch-history.json from a Takeout zip, folder or the file itself."""
    path = Path(path)
    if path.suffix == ".zip":
        with zipfile.ZipFile(path) as z:
            names = [n for n in z.namelist() if n.endswith("watch-history.json")]
            if not names:
                raise SystemExit(f"No watch-history.json in {path.name}. Export YouTube 'history' in JSON format.")
            return json.load(io.TextIOWrapper(z.open(names[0]), encoding="utf-8"))
    if path.is_dir():
        files = sorted(path.rglob("watch-history.json"))
        if not files:
            raise SystemExit(f"No watch-history.json under {path}. Export YouTube 'history' in JSON format.")
        path = files[0]
    if path.suffix != ".json":
        raise SystemExit("Use the JSON format for YouTube history in Takeout (HTML can't be read reliably).")
    return json.loads(path.read_text(encoding="utf-8"))


def parse(entries):
    """YT Music plays as [(ts, title, artist)], oldest first. Skips YouTube videos, and songs that
    were removed (no title or artist left)."""
    out = []
    for e in entries:
        if e.get("header") != "YouTube Music":
            continue
        subs = e.get("subtitles") or []
        title = e.get("title") or ""
        for p in TITLE_PREFIXES:
            if title.startswith(p):
                title = title[len(p):]
                break
        artist = re.sub(r"\s+-\s+Topic$", "", (subs[0].get("name") or "") if subs else "").strip()
        if not artist or not title or title.startswith("http") or not e.get("time"):
            continue
        ts = datetime.fromisoformat(e["time"].replace("Z", "+00:00")).timestamp()
        out.append((int(ts), title.strip(), artist))
    out.sort()
    return out


# ---------- the import ----------

def cutoff(con):
    """History before this is imported: when live YT Music logging started (else now)."""
    first = con.execute("SELECT MIN(ts) FROM plays WHERE source = 'yt'").fetchone()[0]
    return first or int(time.time())


def import_plays(con, plays, info):
    """Replaces earlier imported history with these plays. info: {(title, artist): song info}."""
    con.execute("DELETE FROM plays WHERE source = ?", (SOURCE,))
    rows = []
    for ts, title, artist in plays:
        s = info.get(_key(title, artist)) or {}
        secs = s.get("duration") or AVERAGE
        rows.append((ts, library.local_iso(ts), title, artist, s.get("album") or "", s.get("duration"), secs,
                     None, SOURCE, pid_for(title, artist), ts + int(secs), s.get("genre")))
    con.executemany("""INSERT INTO plays (ts, played_at, title, artist, album, duration, seconds_listened,
                       skipped, source, persistent_id, ended_ts, genre) VALUES (?,?,?,?,?,?,?,?,?,?,?,?)""", rows)
    con.commit()
    return len(rows)


def apply_info(con, title, artist, s):
    """Fills in one song's length, album and genre on its imported rows."""
    secs = s.get("duration")
    con.execute("""UPDATE plays SET duration = ?, seconds_listened = ?, ended_ts = ts + ?,
                   album = CASE WHEN COALESCE(album, '') = '' THEN ? ELSE album END, genre = COALESCE(genre, ?)
                   WHERE source = ? AND persistent_id = ?""",
                (secs, secs or AVERAGE, int(secs or AVERAGE), s.get("album") or "", s.get("genre"),
                 SOURCE, pid_for(title, artist)))


# ---------- song info from Apple ----------

def _key(title, artist):
    return f"{title}\x1f{artist}"


def load_cache():
    try:
        return json.loads((paths.SUPPORT / CACHE).read_text())
    except (OSError, ValueError):
        return {"songs": {}}


def save_cache(cache):
    tmp = paths.SUPPORT / (CACHE + ".tmp")
    tmp.write_text(json.dumps(cache, ensure_ascii=False))
    tmp.replace(paths.SUPPORT / CACHE)


def match(results, title, artist):
    """The result that is this song by this artist (previews.best_match's rule), as song info."""
    t, a = previews._norm(title), previews._norm(artist)
    for r in results:
        rt, ra = previews._norm(r.get("trackName")), previews._norm(r.get("artistName"))
        if rt == t and a and ra and (a in ra or ra in a) and r.get("trackTimeMillis"):
            return {"duration": round(r["trackTimeMillis"] / 1000), "album": r.get("collectionName") or "",
                    "genre": r.get("primaryGenreName") or None, "art": r.get("artworkUrl100")}
    return None


class Apple:
    """iTunes Search, at most one request every GAP seconds; waits a minute when Apple says slow down."""

    def __init__(self, country):
        self.country = country
        self.last = 0.0

    def get(self, url):
        for attempt in range(4):
            time.sleep(max(0.0, self.last + GAP - time.time()))
            self.last = time.time()
            try:
                with urllib.request.urlopen(url, timeout=10) as r:
                    return json.load(r).get("results", [])
            except urllib.error.HTTPError as e:
                if e.code not in (403, 429, 503):
                    raise
                time.sleep(60 * (attempt + 1))
        raise RuntimeError("Apple's search keeps refusing; try again later")

    def artist_songs(self, artist):
        q = urllib.parse.urlencode({"term": artist, "entity": "musicArtist", "limit": 10, "country": self.country})
        found = [a for a in self.get(f"https://itunes.apple.com/search?{q}")
                 if previews._norm(a.get("artistName")) == previews._norm(artist)]
        if not found:
            return []
        q = urllib.parse.urlencode({"id": found[0]["artistId"], "entity": "song", "limit": 200, "country": self.country})
        return [x for x in self.get(f"https://itunes.apple.com/lookup?{q}") if x.get("wrapperType") == "track"]

    def search(self, title, artist):
        q = urllib.parse.urlencode({"term": f"{previews._clean(title)} {artist}", "media": "music", "entity": "song",
                                    "limit": 50, "country": self.country})
        return self.get(f"https://itunes.apple.com/search?{q}")


def save_cover(url, pid):
    """Apple's cover for an imported song, as the 160 px and 640 px JPEGs reports use (skips existing)."""
    base = paths.SUPPORT / "artwork"
    targets = [(base / f"{pid}.jpg", 160), (base / "640" / f"{pid}.jpg", 640)]
    if not url or all(t.exists() for t, _ in targets):
        return
    big = re.sub(r"/\d+x\d+bb\.", "/640x640bb.", url)
    with tempfile.TemporaryDirectory() as tmp:
        raw = Path(tmp) / "cover.jpg"
        with urllib.request.urlopen(big, timeout=10) as r:
            raw.write_bytes(r.read())
        for out, size in targets:
            out.parent.mkdir(parents=True, exist_ok=True)
            if not out.exists():
                subprocess.run(["sips", "-s", "format", "jpeg", "-s", "formatOptions", "85", "-Z", str(size),
                                str(raw), "--out", str(out)], capture_output=True)


def look_up(con, songs, cache, log=print):
    """Finds each song's info (artist catalogue first: two requests cover all of an artist's songs;
    then one search per song still missing), applying it to the imported rows as it goes."""
    apple = Apple(previews.store())
    todo = [s for s in songs if _key(*s) not in cache["songs"]]
    by_artist = {}
    for title, artist in todo:
        by_artist.setdefault(artist, []).append(title)
    done, found = 0, 0
    try:
        for artist, titles in sorted(by_artist.items(), key=lambda kv: -len(kv[1])):
            # One artist search + one catalogue lookup pays off from two songs on.
            catalogue = apple.artist_songs(artist) if len(titles) > 1 else []
            for title in titles:
                s = match(catalogue or [], title, artist) or match(apple.search(title, artist), title, artist)
                cache["songs"][_key(title, artist)] = s or {}
                if s:
                    found += 1
                    apply_info(con, title, artist, s)
                    try:
                        save_cover(s.get("art"), pid_for(title, artist))
                    except OSError:
                        pass
                done += 1
                if done % 10 == 0:
                    con.commit()
                    save_cache(cache)
                    log(f"  {done}/{len(todo)} songs looked up ({found} found)")
    finally:
        con.commit()
        save_cache(cache)
    return done, found
