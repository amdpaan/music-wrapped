"""Aggregations over logged plays (date ranges) and the library (all-time)."""

import re
from collections import Counter, defaultdict, namedtuple
from datetime import date, datetime, timedelta

Play = namedtuple("Play", "ts dt title artist album duration seconds skipped source pid genre ended")
# pid: a track to take the cover from (for artists/albums: their most-played track).
# est: the part of `seconds` that is estimated (other-device plays count as the full track length).
Row = namedtuple("Row", "name sub plays seconds pid est", defaults=(None, 0))

# Sources timed live on this Mac: 'mac' = the Music app, 'yt' = other apps via Now Playing (YT Music,
# browsers). 'other' = inferred from synced play counts. Same list as the logger's liveSources.
LIVE = ("mac", "yt")


# ---------- genres ----------

# Spellings of one genre that should count together, by genre_key(). Anything else with the same key
# (e.g. "Hip Hop" / "hip-hop" / "HipHop") merges too, under the first spelling seen.
GENRE_ALIASES = {
    "hiphop": "Hip-Hop/Rap", "hiphoprap": "Hip-Hop/Rap", "rap": "Hip-Hop/Rap", "raphiphop": "Hip-Hop/Rap",
    "rnb": "R&B/Soul", "randb": "R&B/Soul", "rb": "R&B/Soul", "randbsoul": "R&B/Soul", "rbsoul": "R&B/Soul",
    "rnbsoul": "R&B/Soul",
    "kpop": "K-Pop", "jpop": "J-Pop", "cpop": "C-Pop", "mandopop": "Mandopop", "cantopop": "Cantopop",
    "singersongwriter": "Singer/Songwriter",
    "lofi": "Lo-Fi", "lofihiphop": "Lo-Fi",
    "electronic": "Electronic", "electronica": "Electronic",
    "alternative": "Alternative", "alt": "Alternative",
    "indiepop": "Indie Pop", "indierock": "Indie Rock",
    "soundtrack": "Soundtrack", "soundtracks": "Soundtrack", "ost": "Soundtrack",
}
_FIRST_SPELLING = {}


def genre_key(name):
    """'Hip-Hop/Rap', 'hip hop & rap' -> comparable keys ('&' reads as 'and')."""
    return re.sub(r"[^0-9a-z]+", "", (name or "").lower().replace("&", "and"))


def genre_name(name):
    """One display name per genre, however it's spelled. '' for unknown."""
    name = (name or "").strip()
    key = genre_key(name)
    if not key:
        return ""
    if key in GENRE_ALIASES:
        return GENRE_ALIASES[key]
    return _FIRST_SPELLING.setdefault(key, name)


def ts_of(d):
    """Local midnight of a date (or a datetime) as unix seconds."""
    if isinstance(d, date) and not isinstance(d, datetime):
        d = datetime(d.year, d.month, d.day)
    return int(d.timestamp())


def plays_between(con, start, end):
    """Plays with start time in [start, end), where start/end are dates or datetimes."""
    # Genre: what Music reported for the play, else the library track's (older and other-device plays).
    rows = con.execute(
        """SELECT p.*, COALESCE(NULLIF(p.genre, ''), l.genre) AS g FROM plays p
           LEFT JOIN library l ON l.persistent_id = p.persistent_id
           WHERE p.ts >= ? AND p.ts < ? ORDER BY p.ts""", (ts_of(start), ts_of(end)))
    out = []
    for r in rows:
        secs = r["seconds_listened"] if r["source"] in LIVE else (r["duration"] or r["seconds_listened"])
        out.append(Play(r["ts"], datetime.fromtimestamp(r["ts"]), r["title"], r["artist"] or "Unknown artist",
                        r["album"] or "", r["duration"] or 0, secs or 0, r["skipped"], r["source"],
                        r["persistent_id"], genre_name(r["g"]), r["ended_ts"] or r["ts"]))
    return out


def hours(plays):
    return sum(p.seconds for p in plays) / 3600


def estimated_hours(plays):
    """Hours from other-device plays: the synced play count gives no listening time, so each one
    counts as the full track length (Mac plays are timed live)."""
    return sum(p.seconds for p in plays if p.source not in LIVE) / 3600


def _rank(groups, pids, n):
    """Top n rows; each gets the pid of its most-played track (for artwork)."""
    keys = sorted(groups, key=lambda k: (-groups[k].plays, -groups[k].seconds, groups[k].name.lower()))[:n]
    return [groups[k]._replace(pid=pids[k].most_common(1)[0][0]) if pids[k] else groups[k] for k in keys]


def _group(plays, keyfn, rowfn):
    g, pids = {}, defaultdict(Counter)
    for p in plays:
        k = keyfn(p)
        if k is None:
            continue
        r = g.get(k) or rowfn(p)
        g[k] = r._replace(plays=r.plays + 1, seconds=r.seconds + p.seconds,
                          est=r.est + (p.seconds if p.source not in LIVE else 0))
        if p.pid:
            pids[k][p.pid] += 1
    return g, pids


def top_songs(plays, n):
    g, pids = _group(plays, lambda p: (p.title, p.artist), lambda p: Row(p.title, p.artist, 0, 0))
    return _rank(g, pids, n)


def top_artists(plays, n):
    g, pids = _group(plays, lambda p: p.artist, lambda p: Row(p.artist, "", 0, 0))
    return _rank(g, pids, n)


def top_albums(plays, n):
    g, pids = _group(plays, lambda p: p.album or None, lambda p: Row(p.album, "", 0, 0))
    artists = defaultdict(Counter)
    for p in plays:
        if p.album:
            artists[p.album][p.artist] += 1
    return [r._replace(sub=artists[r.name].most_common(1)[0][0]) for r in _rank(g, pids, n)]


def top_genres(plays, n):
    """Plays with an unknown genre are left out."""
    g, pids = _group(plays, lambda p: p.genre or None, lambda p: Row(p.genre, "", 0, 0))
    return _rank(g, pids, n)


def on_repeat(plays, min_plays=5):
    return [r for r in top_songs(plays, 10_000) if r.plays >= min_plays]


def heatmap(plays):
    """Mac-only minutes listened, [weekday Mon=0][hour]."""
    grid = [[0.0] * 24 for _ in range(7)]
    for p in plays:
        if p.source in LIVE:
            grid[p.dt.weekday()][p.dt.hour] += p.seconds / 60
    return grid


def most_skipped(plays, n=5):
    """Mac-only. Rows of (title, artist, skipped, mac plays)."""
    skipped, total = Counter(), Counter()
    for p in plays:
        if p.source in LIVE:
            total[(p.title, p.artist)] += 1
            if p.skipped:
                skipped[(p.title, p.artist)] += 1
    rows = [(k[0], k[1], s, total[k]) for k, s in skipped.items()]
    rows.sort(key=lambda r: (-r[2], -r[2] / r[3], r[0].lower()))
    return rows[:n]


def known_artists_before(con, start):
    """Artists we know were listened to (or in the library) before `start`."""
    t = ts_of(start)
    known = {r[0] for r in con.execute("SELECT DISTINCT artist FROM plays WHERE ts < ?", (t,))}
    known |= {r[0] for r in con.execute(
        "SELECT DISTINCT artist FROM library WHERE added_ts < ? OR played_ts < ?", (t, t))}
    # Plays already in the library at backfill time can't be dated (and "date added" resets when
    # a song is re-added), so an artist with any of them never counts as new.
    # Tracks first seen later also get a baseline; those plays came before first_seen_ts.
    known |= {r[0] for r in con.execute(
        """SELECT DISTINCT artist FROM library WHERE baseline_play_count > 0 AND (first_seen_ts < ?
           OR first_seen_ts <= (SELECT MIN(ts) FROM snapshots WHERE kind = 'backfill'))""", (t,))}
    return {(a or "").lower() for a in known}


def new_artists(con, plays, start, n=10):
    known = known_artists_before(con, start)
    return [r for r in top_artists(plays, 10_000) if r.name.lower() not in known][:n]


def longest_streak(plays):
    """Longest run of consecutive days with at least one play: (days, first day, last day)."""
    days = sorted({p.dt.date() for p in plays})
    best = (0, None, None)
    run_start = prev = None
    for d in days:
        if prev is not None and d == prev + timedelta(days=1):
            pass
        else:
            run_start = d
        length = (d - run_start).days + 1
        if length > best[0]:
            best = (length, run_start, d)
        prev = d
    return best


def streak_until(con, last_day):
    """Days in a row with at least one logged play, ending on last_day (or the day before, if
    nothing was played on last_day yet): (days, first day, last day)."""
    t = ts_of(last_day + timedelta(days=1))
    days = {datetime.fromtimestamp(r[0]).date() for r in con.execute("SELECT ts FROM plays WHERE ts < ?", (t,))}
    d = last_day if last_day in days else last_day - timedelta(days=1)
    end = d
    while d in days:
        d -= timedelta(days=1)
    n = (end - d).days
    return (n, d + timedelta(days=1), end) if n else (0, None, None)


def longest_session(plays, gap=10 * 60):
    """Mac only: the longest stretch of back-to-back listening (a new session starts after a gap of
    more than 10 minutes). (start datetime, end datetime, songs) or None."""
    best, cur = None, None
    for p in sorted((p for p in plays if p.source in LIVE), key=lambda p: p.ts):
        if cur and p.ts - cur[1] <= gap:
            cur = (cur[0], max(cur[1], p.ended), cur[2] + 1)
        else:
            cur = (p.ts, p.ended, 1)
        if not best or cur[1] - cur[0] > best[1] - best[0]:
            best = cur
    if not best:
        return None
    return datetime.fromtimestamp(best[0]), datetime.fromtimestamp(best[1]), best[2]


def most_replayed_day(plays, min_plays=3):
    """The song played most times on a single day: (Row, date) or None. All devices."""
    days = Counter((p.dt.date(), p.title, p.artist) for p in plays)
    if not days:
        return None
    (day, title, artist), n = max(days.items(), key=lambda kv: (kv[1], kv[0][0]))
    if n < min_plays:
        return None
    pid = Counter(p.pid for p in plays if p.title == title and p.artist == artist and p.pid).most_common(1)
    return Row(title, artist, n, 0, pid[0][0] if pid else None), day


def week_buckets(start, end):
    """ISO weeks (Mon–Sun) overlapping [start, end), clipped to the range: [(label, s, e)]."""
    out = []
    s = start - timedelta(days=start.weekday())
    while s < end:
        e = s + timedelta(days=7)
        cs, ce = max(s, start), min(e, end)
        y, w, _ = s.isocalendar()
        out.append((f"W{w:02d}", cs, ce))
        s = e
    return out


def split(plays, buckets):
    """Plays per bucket from week_buckets()."""
    res = []
    for label, s, e in buckets:
        a, b = ts_of(s), ts_of(e)
        res.append((label, s, e, [p for p in plays if a <= p.ts < b]))
    return res


def library_top(con, kind, n):
    """All-time top songs/artists/albums from library play counts."""
    base = "FROM library l WHERE in_library = 1 AND play_count > 0"
    top_pid = ("(SELECT persistent_id FROM library t WHERE t.in_library = 1 AND t.{col} = l.{col} "
               "ORDER BY t.play_count DESC LIMIT 1)")
    if kind == "songs":
        q = f"SELECT title, artist, play_count, play_count * COALESCE(duration, 0), persistent_id {base} ORDER BY 3 DESC, 4 DESC LIMIT ?"
    elif kind == "genres":
        # Grouped by spelling in SQL, then spellings of the same genre are merged here.
        q = (f"SELECT genre, '', SUM(play_count), SUM(play_count * COALESCE(duration, 0)), {top_pid.format(col='genre')} "
             f"{base} AND COALESCE(genre, '') != '' GROUP BY genre ORDER BY 3 DESC, 4 DESC")
        merged = {}
        for r in con.execute(q):
            name = genre_name(r[0])
            m = merged.get(name)
            # Each spelling's rows arrive most-played first, so the first one keeps its cover track.
            merged[name] = Row(name, "", r[2], r[3], r[4]) if not m else m._replace(plays=m.plays + r[2], seconds=m.seconds + r[3])
        rows = sorted(merged.values(), key=lambda r: (-r.plays, -r.seconds, r.name.lower()))
        return rows[:n]
    elif kind == "artists":
        q = (f"SELECT artist, '', SUM(play_count), SUM(play_count * COALESCE(duration, 0)), {top_pid.format(col='artist')} "
             f"{base} AND artist != '' GROUP BY artist ORDER BY 3 DESC, 4 DESC LIMIT ?")
    else:
        q = (f"SELECT album, MAX(artist), SUM(play_count), SUM(play_count * COALESCE(duration, 0)), {top_pid.format(col='album')} "
             f"{base} AND album != '' GROUP BY album ORDER BY 3 DESC, 4 DESC LIMIT ?")
    return [Row(r[0], r[1], r[2], r[3], r[4]) for r in con.execute(q, (n,))]


def library_totals(con):
    r = con.execute("""SELECT COUNT(*), COALESCE(SUM(play_count), 0), COALESCE(SUM(play_count * COALESCE(duration, 0)), 0),
                       COUNT(DISTINCT artist) FROM library WHERE in_library = 1""").fetchone()
    return {"tracks": r[0], "plays": r[1], "hours": r[2] / 3600, "artists": r[3]}


def logged_totals(con):
    r = con.execute("""SELECT COUNT(*), COALESCE(SUM(CASE WHEN source IN ('mac','yt') THEN seconds_listened
                       ELSE COALESCE(duration, seconds_listened) END), 0), MIN(ts),
                       SUM(source='mac'), SUM(source='other'), SUM(source='yt') FROM plays""").fetchone()
    return {"plays": r[0], "hours": r[1] / 3600, "since": datetime.fromtimestamp(r[2]) if r[2] else None,
            "mac": r[3] or 0, "other": r[4] or 0, "yt": r[5] or 0}


# ---------- listening personality ----------

PERSONALITIES = {
    # name: (one-line description template, trait label)
    "The Loyalist": ("{pct}% of your plays were {artist}. You know what you like.", "loyal to {artist}"),
    "On Repeat": ("You played {song} {n} times. Some songs are worth hearing again and again.", "replayer"),
    "The Explorer": ("{n} artists were new to you. Always looking for the next favourite.", "explorer"),
    "Night Owl": ("{pct}% of your listening happened between 10 pm and 4 am.", "night owl"),
    "Early Bird": ("{pct}% of your listening happened between 5 and 9 am.", "early bird"),
    "Weekend Warrior": ("{pct}% of your listening happened on Saturdays and Sundays.", "weekend listener"),
    "Genre Hopper": ("{n} genres, and none of them more than a third of your plays.", "genre hopper"),
    "Daily Devotee": ("Music on {n} of {days} days. It's part of your routine.", "every day"),
    "The All-Rounder": ("A bit of everything, any time of day. No single habit runs your listening.", "all-rounder"),
}


def personality(plays, new_artist_count=0, days_in_period=7):
    """(name, description, [other traits]) from the habits that stand out most, or None without plays.
    Each habit gets a score: how far it is past its threshold (1.0 = exactly at it). The highest one
    names you; the next two that also pass are shown as traits. Time-of-day habits use Mac plays only."""
    if len(plays) < 5:
        return None
    n = len(plays)
    cands = []
    top_a = top_artists(plays, 1)[0]
    share = top_a.plays / n
    cands.append((share / 0.35, "The Loyalist", {"pct": round(share * 100), "artist": top_a.name}))
    top_s = top_songs(plays, 1)[0]
    cands.append((top_s.plays / max(8, n * 0.15), "On Repeat", {"song": top_s.name, "n": top_s.plays}))
    artists = len({p.artist for p in plays})
    if new_artist_count:
        cands.append((min(new_artist_count / 5, new_artist_count / max(1, artists) / 0.3), "The Explorer", {"n": new_artist_count}))
    mac = [p for p in plays if p.source in LIVE]
    secs = sum(p.seconds for p in mac) or 1
    if len(mac) >= 5:
        night = sum(p.seconds for p in mac if p.dt.hour >= 22 or p.dt.hour < 4) / secs
        early = sum(p.seconds for p in mac if 5 <= p.dt.hour < 9) / secs
        cands.append((night / 0.4, "Night Owl", {"pct": round(night * 100)}))
        cands.append((early / 0.35, "Early Bird", {"pct": round(early * 100)}))
    weekend = sum(p.seconds for p in plays if p.dt.weekday() >= 5) / (sum(p.seconds for p in plays) or 1)
    if days_in_period >= 7:
        cands.append((weekend / 0.5, "Weekend Warrior", {"pct": round(weekend * 100)}))
    genres = top_genres(plays, 10_000)
    known = sum(r.plays for r in genres)
    if known:
        cands.append((min(len(genres) / 6, (1 / 3) / (genres[0].plays / known)), "Genre Hopper", {"n": len(genres)}))
    days = len({p.dt.date() for p in plays})
    if days_in_period >= 7:
        cands.append(((days / days_in_period) / 0.85, "Daily Devotee", {"n": days, "days": days_in_period}))
    cands.sort(key=lambda c: -c[0])
    passing = [c for c in cands if c[0] >= 1]
    if not passing:
        return "The All-Rounder", PERSONALITIES["The All-Rounder"][0], []
    score, name, vals = passing[0]
    traits = [PERSONALITIES[nm][1].format(**v) for _, nm, v in passing[1:3]]
    return name, PERSONALITIES[name][0].format(**vals), traits


def first_play(plays):
    """The first logged play of a period (for the yearly Wrapped), or None."""
    return min(plays, key=lambda p: p.ts) if plays else None
