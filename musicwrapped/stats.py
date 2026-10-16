"""Aggregations over logged plays (date ranges) and the library (all-time)."""

from collections import Counter, defaultdict, namedtuple
from datetime import date, datetime, timedelta

Play = namedtuple("Play", "ts dt title artist album duration seconds skipped source")
Row = namedtuple("Row", "name sub plays seconds")


def ts_of(d):
    """Local midnight of a date (or a datetime) as unix seconds."""
    if isinstance(d, date) and not isinstance(d, datetime):
        d = datetime(d.year, d.month, d.day)
    return int(d.timestamp())


def plays_between(con, start, end):
    """Plays with start time in [start, end), where start/end are dates or datetimes."""
    rows = con.execute(
        "SELECT * FROM plays WHERE ts >= ? AND ts < ? ORDER BY ts", (ts_of(start), ts_of(end)))
    out = []
    for r in rows:
        secs = r["seconds_listened"] if r["source"] == "mac" else (r["duration"] or r["seconds_listened"])
        out.append(Play(r["ts"], datetime.fromtimestamp(r["ts"]), r["title"], r["artist"] or "Unknown artist",
                        r["album"] or "", r["duration"] or 0, secs or 0, r["skipped"], r["source"]))
    return out


def hours(plays):
    return sum(p.seconds for p in plays) / 3600


def _rank(groups, n):
    rows = sorted(groups.values(), key=lambda r: (-r.plays, -r.seconds, r.name.lower()))
    return rows[:n]


def top_songs(plays, n):
    g = {}
    for p in plays:
        k = (p.title, p.artist)
        r = g.get(k) or Row(p.title, p.artist, 0, 0)
        g[k] = r._replace(plays=r.plays + 1, seconds=r.seconds + p.seconds)
    return _rank(g, n)


def top_artists(plays, n):
    g = {}
    for p in plays:
        r = g.get(p.artist) or Row(p.artist, "", 0, 0)
        g[p.artist] = r._replace(plays=r.plays + 1, seconds=r.seconds + p.seconds)
    return _rank(g, n)


def top_albums(plays, n):
    g, artists = {}, defaultdict(Counter)
    for p in plays:
        if not p.album:
            continue
        r = g.get(p.album) or Row(p.album, "", 0, 0)
        g[p.album] = r._replace(plays=r.plays + 1, seconds=r.seconds + p.seconds)
        artists[p.album][p.artist] += 1
    rows = _rank(g, n)
    return [r._replace(sub=artists[r.name].most_common(1)[0][0]) for r in rows]


def on_repeat(plays, min_plays=5):
    return [r for r in top_songs(plays, 10_000) if r.plays >= min_plays]


def heatmap(plays):
    """Mac-only minutes listened, [weekday Mon=0][hour]."""
    grid = [[0.0] * 24 for _ in range(7)]
    for p in plays:
        if p.source == "mac":
            grid[p.dt.weekday()][p.dt.hour] += p.seconds / 60
    return grid


def most_skipped(plays, n=5):
    """Mac-only. Rows of (title, artist, skipped, mac plays)."""
    skipped, total = Counter(), Counter()
    for p in plays:
        if p.source == "mac":
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
    # Plays already counted at backfill time happened before the backfill.
    known |= {r[0] for r in con.execute(
        "SELECT DISTINCT artist FROM library WHERE baseline_play_count > 0 AND first_seen_ts < ?", (t,))}
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
    base = "FROM library WHERE in_library = 1 AND play_count > 0"
    if kind == "songs":
        q = f"SELECT title, artist, play_count, play_count * COALESCE(duration, 0) {base} ORDER BY 3 DESC, 4 DESC LIMIT ?"
    elif kind == "artists":
        q = f"SELECT artist, '', SUM(play_count), SUM(play_count * COALESCE(duration, 0)) {base} AND artist != '' GROUP BY artist ORDER BY 3 DESC, 4 DESC LIMIT ?"
    else:
        q = (f"SELECT album, MAX(artist), SUM(play_count), SUM(play_count * COALESCE(duration, 0)) {base} AND album != '' "
             "GROUP BY album ORDER BY 3 DESC, 4 DESC LIMIT ?")
    return [Row(r[0], r[1], r[2], r[3]) for r in con.execute(q, (n,))]


def library_totals(con):
    r = con.execute("""SELECT COUNT(*), COALESCE(SUM(play_count), 0), COALESCE(SUM(play_count * COALESCE(duration, 0)), 0),
                       COUNT(DISTINCT artist) FROM library WHERE in_library = 1""").fetchone()
    return {"tracks": r[0], "plays": r[1], "hours": r[2] / 3600, "artists": r[3]}


def logged_totals(con):
    r = con.execute("""SELECT COUNT(*), COALESCE(SUM(CASE WHEN source='mac' THEN seconds_listened
                       ELSE COALESCE(duration, seconds_listened) END), 0), MIN(ts),
                       SUM(source='mac'), SUM(source='other') FROM plays""").fetchone()
    return {"plays": r[0], "hours": r[1] / 3600, "since": datetime.fromtimestamp(r[2]) if r[2] else None,
            "mac": r[3] or 0, "other": r[4] or 0}
