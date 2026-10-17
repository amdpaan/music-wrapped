"""Song previews for Play story (opt-in: `music-wrapped previews on`).

When it's on, building a report looks up its top songs in Apple's public iTunes Search API (no account
or key) and keeps each song's 30-second preview URL. Play story then plays them: the top song on its
slide, the top artist's best song on theirs, and so on. Lookups send the song title and artist name to
Apple; nothing else. Results are cached in previews.json (misses are retried after a week), so a
report rebuild normally makes no requests at all.
"""

import json
import re
import subprocess
import time
import urllib.parse
import urllib.request

from . import paths

CACHE = "previews.json"
VERSION = "3"   # bump to retry cached misses after a lookup change
HIT_DAYS, MISS_DAYS = 30, 7
TIMEOUT = 4


def _config():
    try:
        return json.loads(paths.CONFIG.read_text())
    except (OSError, ValueError):
        return {}


def enabled():
    return bool(_config().get("previews"))


def set_enabled(on):
    cfg = _config()
    cfg["previews"] = bool(on)
    paths.CONFIG.parent.mkdir(parents=True, exist_ok=True)
    paths.CONFIG.write_text(json.dumps(cfg, indent=2))


def store():
    """Two-letter App Store country: config.json "store", else the Mac's region (en_MY -> MY), else US."""
    cfg = _config().get("store")
    if cfg and re.fullmatch(r"[A-Za-z]{2}", cfg):
        return cfg.upper()
    try:
        loc = subprocess.run(["defaults", "read", "-g", "AppleLocale"], capture_output=True, text=True, timeout=3).stdout
        m = re.search(r"_([A-Z]{2})", loc)
        if m:
            return m[1]
    except (OSError, subprocess.SubprocessError):
        pass
    return "US"


def _clean(title):
    """'Glass Ocean (feat. Mira Sol)' -> 'Glass Ocean': extra words only confuse the search."""
    return re.sub(r"\s*[(\[].*?[)\]]|\s+-\s+.*$", "", title or "").strip() or (title or "")


def _search(params):
    q = urllib.parse.urlencode(dict(params, media="music", entity="song"))
    with urllib.request.urlopen(f"https://itunes.apple.com/search?{q}", timeout=TIMEOUT) as r:
        return json.load(r).get("results", [])


def _artist_songs(artist, country):
    """Up to 200 songs from the artist's catalogue (Apple ID found by an exact name match), or []."""
    q = urllib.parse.urlencode({"term": artist, "entity": "musicArtist", "limit": 10, "country": country})
    with urllib.request.urlopen(f"https://itunes.apple.com/search?{q}", timeout=TIMEOUT) as r:
        found = [a for a in json.load(r).get("results", []) if _norm(a.get("artistName")) == _norm(artist)]
    if not found:
        return []
    q = urllib.parse.urlencode({"id": found[0]["artistId"], "entity": "song", "limit": 200, "country": country})
    with urllib.request.urlopen(f"https://itunes.apple.com/lookup?{q}", timeout=TIMEOUT) as r:
        return [x for x in json.load(r).get("results", []) if x.get("wrapperType") == "track"]


def _norm(s):
    """Lowercase, no '(feat. …)' / '[Remastered]' / '- Single Version', letters and digits only."""
    s = re.sub(r"\s*[(\[].*?[)\]]", "", (s or "").lower())
    s = re.sub(r"\s+-\s+.*$", "", s)
    return re.sub(r"[^0-9a-z]+", "", s.replace("&", "and"))


def best_match(results, title, artist):
    """The preview URL of the result that is this song by this artist, or None (never a different song)."""
    t, a = _norm(title), _norm(artist)
    for r in results:
        rt, ra = _norm(r.get("trackName")), _norm(r.get("artistName"))
        if r.get("previewUrl") and rt == t and (a in ra or ra in a) and a and ra:
            return r["previewUrl"]
    return None


def _load():
    try:
        return json.loads((paths.SUPPORT / CACHE).read_text())
    except (OSError, ValueError):
        return {}


def _save(cache):
    cache = {k: v for k, v in cache.items() if k.startswith(f"v{VERSION}|")}
    tmp = paths.SUPPORT / (CACHE + ".tmp")
    tmp.write_text(json.dumps(cache, indent=1, ensure_ascii=False))
    tmp.replace(paths.SUPPORT / CACHE)


def lookup(title, artist, cache=None, country=None):
    """Preview URL for a song, from the cache or Apple's search (None if not found or offline)."""
    own = cache is None
    cache = _load() if own else cache
    key = f"v{VERSION}|{(country or '').upper()}|{title}|{artist}"
    hit = cache.get(key)
    now = time.time()
    if hit and now - hit["ts"] < (HIT_DAYS if hit.get("url") else MISS_DAYS) * 86400:
        return hit.get("url")
    # Apple ranks search results by popularity, so a famous artist's other hits can crowd out the song
    # (a well-known band's album track never showed up). So: a plain search first, then the artist's own
    # catalogue (their Apple ID, then up to 200 of their songs), then the title alone.
    country = country or store()
    url = None
    try:
        steps = (lambda: _search({"term": f"{_clean(title)} {artist}", "limit": 50, "country": country}),
                 lambda: _artist_songs(artist, country),
                 lambda: _search({"term": _clean(title), "attribute": "songTerm", "limit": 200, "country": country}))
        for step in steps:
            url = best_match(step(), title, artist)
            if url:
                break
    except Exception:   # offline, rate-limited, bad JSON: try again next time
        return hit.get("url") if hit else None
    cache[key] = {"url": url, "ts": int(now)}
    if own:
        _save(cache)
    return url


def for_songs(pairs):
    """{(title, artist): url} for the songs that have a preview. Empty when previews are off."""
    if not enabled() or not pairs:
        return {}
    cache, country, out = _load(), store(), {}
    for title, artist in dict.fromkeys(pairs):
        url = lookup(title, artist, cache, country)
        if url:
            out[(title, artist)] = url
    try:
        _save(cache)
    except OSError:
        pass
    return out
