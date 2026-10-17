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
    tmp = paths.SUPPORT / (CACHE + ".tmp")
    tmp.write_text(json.dumps(cache, indent=1, ensure_ascii=False))
    tmp.replace(paths.SUPPORT / CACHE)


def lookup(title, artist, cache=None, country=None):
    """Preview URL for a song, from the cache or Apple's search (None if not found or offline)."""
    own = cache is None
    cache = _load() if own else cache
    key = f"{(country or '').upper()}|{title}|{artist}"
    hit = cache.get(key)
    now = time.time()
    if hit and now - hit["ts"] < (HIT_DAYS if hit.get("url") else MISS_DAYS) * 86400:
        return hit.get("url")
    q = urllib.parse.urlencode({"term": f"{artist} {title}", "media": "music", "entity": "song", "limit": 10,
                                "country": country or store()})
    try:
        with urllib.request.urlopen(f"https://itunes.apple.com/search?{q}", timeout=TIMEOUT) as r:
            results = json.load(r).get("results", [])
    except Exception:   # offline, rate-limited, bad JSON: try again next time
        return hit.get("url") if hit else None
    url = best_match(results, title, artist)
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
