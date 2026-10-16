"""Builds and saves the weekly / monthly / yearly / all-time / custom reports."""

import calendar
import re
import shutil
from datetime import date, datetime, timedelta

from . import artwork, paths, render as R, stats as S

ALL_DEVICES = "All devices"
MAC_ONLY = "Mac only"


# ---------- periods ----------

def week_of(d):
    start = d - timedelta(days=d.weekday())
    return start, start + timedelta(days=7)


def parse_week(s):
    m = re.fullmatch(r"(\d{4})-?W(\d{1,2})", s.strip(), re.I)
    if not m:
        raise ValueError("week must look like 2026-W42")
    return date.fromisocalendar(int(m[1]), int(m[2]), 1)


def month_bounds(y, m):
    start = date(y, m, 1)
    end = date(y + (m == 12), m % 12 + 1, 1)
    return start, end


def fmt_range(start, end_excl):
    last = end_excl - timedelta(days=1)
    if start.year != last.year:
        return f"{start:%-d %b %Y} – {last:%-d %b %Y}"
    if start.month != last.month:
        return f"{start:%-d %b} – {last:%-d %b %Y}"
    return f"{start:%-d} – {last:%-d %b %Y}"


def clip_now(end):
    """Exclusive end for 'so far' periods: tomorrow, if the period hasn't ended yet."""
    tomorrow = date.today() + timedelta(days=1)
    return min(end, tomorrow)


# ---------- shared bits ----------

def device_split(plays):
    mac = sum(1 for p in plays if p.source == "mac")
    return mac, len(plays) - mac


def footer(con, extra=""):
    lt = S.logged_totals(con)
    since = f"Logging since <b>{lt['since']:%-d %b %Y}</b>. " if lt["since"] else "No plays logged yet. "
    return (since + "Top lists and hours include <b>all devices</b>: Mac plays are logged live; plays on other devices "
            "(e.g. iPhone) are inferred from synced play counts, with hours estimated from track length and times "
            "approximate. Heatmap and skips are <b>Mac only</b>. " + extra)


def top_cards(plays, n, theme_songs="green", theme_artists="pink", theme_albums="purple"):
    return (R.card(f"Top {n} songs", R.ranked(S.top_songs(plays, n)), theme_songs, badge=ALL_DEVICES)
            + R.card(f"Top {n} artists", R.ranked(S.top_artists(plays, n), round_=True), theme_artists, badge=ALL_DEVICES)
            + R.card(f"Top {n} albums", R.ranked(S.top_albums(plays, n)), theme_albums, badge=ALL_DEVICES))


def hero_stats(plays, compare=None):
    mac, other = device_split(plays)
    h = S.hours(plays)
    st = [("hours listened", f"{h:,.1f}") if h >= 1 else ("listened", R.fmt_hours(h)),
          ("plays", f"{len(plays):,}"),
          ("artists", f"{len({p.artist for p in plays}):,}")]
    if compare:
        st.append(compare)
    st.append(("Mac · other devices", f"{mac} · {other}"))
    return st


def week_bars(plays, start, end):
    series = []
    for label, s, e_, ps in S.split(plays, S.week_buckets(start, end)):
        h = S.hours(ps)
        series.append((f"{label}", h, f"{label} ({fmt_range(s, e_)}): {h:.1f} h · {R.fmt_plays(len(ps))}"))
    return series


def artist_changes(plays, start, end, n=5):
    top = [r.name for r in S.top_artists(plays, n)]
    weeks = S.split(plays, S.week_buckets(start, end))
    data = {a: {} for a in top}
    for label, _, _, ps in weeks:
        ranking = {r.name: (i + 1, r.plays) for i, r in enumerate(S.top_artists(ps, 10_000))}
        for a in top:
            data[a][label] = ranking.get(a, (None, 0))
    return R.rank_grid(top, [w[0] for w in weeks], data)


# ---------- reports ----------

def weekly(con, week_start):
    start, end = week_of(week_start)
    y, w, _ = start.isocalendar()
    name = f"{y}-W{w:02d}"
    plays = S.plays_between(con, start, end)
    prev = S.plays_between(con, start - timedelta(days=7), start)
    h, ph = S.hours(plays), S.hours(prev)

    repeat = [(r.name, r.sub, R.fmt_plays(r.plays)) for r in S.on_repeat(plays, 5)]
    skipped = [(t, a, f"{s} of {n} skipped") for t, a, s, n in S.most_skipped(plays)]
    new = [(r.name, "first time this week", R.fmt_plays(r.plays)) for r in S.new_artists(con, plays, start)]
    body = (top_cards(plays, 5)
            + R.card("When you listened", R.heatmap(S.heatmap(plays)), "dark",
                     note="Minutes per hour, Monday to Sunday", badge=MAC_ONLY, wide=True)
            + R.card("On repeat", R.simple_list(repeat, "No song hit 5 plays this week."), "orange",
                     note="Songs with 5+ plays", badge=ALL_DEVICES)
            + R.card("Most skipped", R.simple_list(skipped, "No skips logged. Every song earned its spot."), "blue",
                     note="Stopped before the halfway mark", badge=MAC_ONLY)
            + R.card("New artists", R.simple_list(new, "No new artists this week."), "yellow",
                     note="Artists you hadn't played before", badge=ALL_DEVICES))
    stats = hero_stats(plays, ("vs last week", _pct(h, ph)))
    html = R.page(f"Wrapped {name}", f"Your week in music · {name}", "Your Week, Wrapped",
                  fmt_range(start, end), stats, body,
                  footer(con, f"Last week: <b>{R.fmt_hours(ph)}</b>."), live=date.today() < end)
    return "weekly", name, html


def _pct(h, ph):
    if ph <= 0:
        return "–"
    pct = (h - ph) / ph * 100
    return f"{'+' if pct >= 0 else ''}{pct:.0f}%"


def monthly(con, y, m, so_far=False):
    start, end = month_bounds(y, m)
    q_end = clip_now(end) if so_far else end
    name = f"{y}-{m:02d}"
    plays = S.plays_between(con, start, q_end)
    ps, pe = month_bounds(y - (m == 1), (m - 2) % 12 + 1)
    ph = S.hours(S.plays_between(con, ps, pe))
    title = f"{calendar.month_name[m]} {y}"
    body = (top_cards(plays, 10)
            + R.card("Hours per week", R.bars(week_bars(plays, start, q_end)), "dark",
                     note="Listening hours in each week of the month (weeks start Monday)", badge=ALL_DEVICES, wide=True)
            + R.card("How your top artists moved", artist_changes(plays, start, q_end), "dark",
                     note="Your month's top 5 artists, ranked week by week", badge=ALL_DEVICES, wide=True))
    html = R.page(f"Wrapped {title}", "Your month in music" + (" · so far" if so_far else ""), title,
                  fmt_range(start, q_end), hero_stats(plays, None if so_far else ("vs last month", _pct(S.hours(plays), ph))), body,
                  footer(con))
    return "monthly", name, html


def yearly(con, y):
    start, end = date(y, 1, 1), date(y, 12, 1)  # Jan–Nov
    q_end = clip_now(end)
    plays = S.plays_between(con, start, q_end)
    top_song = S.top_songs(plays, 1)
    streak, s_from, s_to = S.longest_streak(plays)
    disc = S.new_artists(con, plays, start, 1)

    month_items, month_hours = [], []
    for m in range(1, 12):
        ms, me = month_bounds(y, m)
        if ms >= q_end:  # don't show months that haven't started yet
            break
        mp = [p for p in plays if S.ts_of(ms) <= p.ts < S.ts_of(me)]
        t = S.top_songs(mp, 1)
        month_items.append((calendar.month_abbr[m], t[0].name, t[0].sub, t[0].plays, t[0].pid) if t
                           else (calendar.month_abbr[m], None, None, 0, None))
        hh = S.hours(mp)
        month_hours.append((calendar.month_abbr[m], hh, f"{calendar.month_name[m]}: {hh:.1f} h · {R.fmt_plays(len(mp))}"))

    body = (R.card("Your top song", R.headline(top_song[0].name, f"{top_song[0].sub} · {R.fmt_plays(top_song[0].plays)}", top_song[0].pid, art=True)
                   if top_song else R.headline("—", "No plays logged yet"), "green", badge=ALL_DEVICES)
            + R.card("Longest streak", R.headline(f"{streak} day" + ("" if streak == 1 else "s"),
                     f"{s_from:%-d %b} – {s_to:%-d %b}" if streak else "No plays logged yet"), "orange",
                     note="Consecutive days with music")
            + R.card("Biggest new discovery", R.headline(disc[0].name, f"{R.fmt_plays(disc[0].plays)} · {R.fmt_hours(disc[0].seconds / 3600)}",
                                         disc[0].pid, round_=True, art=True)
                     if disc else R.headline("—", "No new artists this year"), "pink",
                     note="Most-played artist you hadn't played before this year")
            + top_cards(plays, 10, "teal", "lilac", "purple")
            + R.card("Top song of each month", R.months(month_items), "blue", badge=ALL_DEVICES, wide=True)
            + R.card("Hours per month", R.bars(month_hours), "dark", badge=ALL_DEVICES, wide=True))
    html = R.page(f"Wrapped {y}", f"{y} Wrapped · January to November", f"Your {y}, Wrapped",
                  fmt_range(start, q_end), hero_stats(plays), body, footer(con))
    return "yearly", str(y), html


def alltime(con):
    lib = S.library_totals(con)
    lt = S.logged_totals(con)
    songs = S.library_top(con, "songs", 25)
    artists = S.library_top(con, "artists", 25)
    albums = S.library_top(con, "albums", 25)
    body = (R.card("Top 25 songs", R.ranked(songs, "Run a backfill first."), "green")
            + R.card("Top 25 artists", R.ranked(artists, "Run a backfill first.", round_=True), "pink")
            + R.card("Top 25 albums", R.ranked(albums, "Run a backfill first."), "purple"))
    stats = [("library plays", f"{lib['plays']:,}"),
             ("est. hours (library)", f"{lib['hours']:,.0f}"),
             ("hours logged", f"{lt['hours']:,.1f}"),
             ("plays logged", f"{lt['plays']:,}"),
             ("artists", f"{lib['artists']:,}")]
    note = ("All-time rankings use your Music library's play counts (every device, since you added each song); "
            "hours there are estimated as plays × track length. ")
    html = R.page("Wrapped All Time", "All time", "Your All-Time, Wrapped",
                  f"{lib['tracks']:,} tracks in your library", stats, body, footer(con, note))
    return "alltime", date.today().isoformat(), html


def custom(con, start, end_incl, label=None):
    end = end_incl + timedelta(days=1)
    plays = S.plays_between(con, start, end)
    streak, s_from, s_to = S.longest_streak(plays)
    repeat = [(r.name, r.sub, R.fmt_plays(r.plays)) for r in S.on_repeat(plays, 5)[:10]]
    skipped = [(t, a, f"{s} of {n} skipped") for t, a, s, n in S.most_skipped(plays)]
    new = [(r.name, "new in this period", R.fmt_plays(r.plays)) for r in S.new_artists(con, plays, start)]
    body = (top_cards(plays, 10)
            + R.card("Hours per week", R.bars(week_bars(plays, start, end)), "dark", badge=ALL_DEVICES, wide=True)
            + R.card("When you listened", R.heatmap(S.heatmap(plays)), "dark",
                     note="Minutes per hour, Monday to Sunday", badge=MAC_ONLY, wide=True)
            + R.card("Longest streak", R.headline(f"{streak} day" + ("" if streak == 1 else "s"),
                     f"{s_from:%-d %b} – {s_to:%-d %b}" if streak else "No plays logged"), "orange")
            + R.card("New artists", R.simple_list(new, "No new artists in this period."), "yellow", badge=ALL_DEVICES)
            + R.card("On repeat", R.simple_list(repeat, "No song hit 5 plays."), "teal", note="Songs with 5+ plays")
            + R.card("Most skipped", R.simple_list(skipped, "No skips logged."), "blue", badge=MAC_ONLY))
    slug = re.sub(r"[^a-z0-9]+", "-", label.lower()).strip("-") if label else ""
    name = f"{start}_to_{end_incl}" + (f"_{slug}" if slug else "")
    html = R.page(f"Wrapped {label or name}", "Custom Wrapped", label or "Your Wrapped",
                  fmt_range(start, end), hero_stats(plays), body, footer(con))
    return "custom", name, html


# ---------- output ----------

def save(kind, name, html):
    folder = paths.REPORTS / kind
    folder.mkdir(parents=True, exist_ok=True)
    out = folder / f"{name}.html"
    out.write_text(artwork.inject(html), encoding="utf-8")
    shutil.copyfile(out, folder / "latest.html")
    write_index()
    return out


def _label(kind, name):
    """(title, subtitle) for a saved report's file name."""
    try:
        if kind == "weekly":
            start = parse_week(name)
            return f"Week {start.isocalendar()[1]}, {start.isocalendar()[0]}", fmt_range(start, start + timedelta(days=7))
        if kind == "monthly":
            y, m = map(int, name.split("-"))
            return f"{calendar.month_name[m]} {y}", ""
        if kind == "yearly":
            return f"{name} Wrapped", "January – November"
        if kind == "alltime":
            return "All time", f"as of {date.fromisoformat(name):%-d %b %Y}"
        if kind == "custom":
            m = re.fullmatch(r"(\d{4}-\d{2}-\d{2})_to_(\d{4}-\d{2}-\d{2})(?:_(.+))?", name)
            s, e_ = date.fromisoformat(m[1]), date.fromisoformat(m[2])
            title = m[3].replace("-", " ").title() if m[3] else "Custom range"
            return title, fmt_range(s, e_ + timedelta(days=1))
    except (ValueError, TypeError, IndexError):
        pass
    return name, ""


def write_index():
    """reports/index.html: every saved report, newest first."""
    sections, counts = [], []
    themes = {"weekly": "green", "monthly": "pink", "yearly": "purple", "alltime": "orange", "custom": "blue"}
    titles = {"weekly": "Weekly", "monthly": "Monthly", "yearly": "Yearly", "alltime": "All time", "custom": "Custom"}
    for kind in paths.REPORT_KINDS:
        folder = paths.REPORTS / kind
        files = [p for p in folder.glob("*.html") if p.name != "latest.html"] if folder.exists() else []
        files.sort(key=lambda p: (p.stat().st_mtime if kind == "custom" else 0, p.stem), reverse=True)
        items = []
        for p in files:
            title, sub = _label(kind, p.stem)
            updated = datetime.fromtimestamp(p.stat().st_mtime)
            items.append((f"{kind}/{p.name}", title, sub, f"{updated:%-d %b}"))
        counts.append((titles[kind].lower(), str(len(files))))
        sections.append(R.card(titles[kind], R.links(items, "No reports yet."), themes[kind],
                               note=f"{len(files)} report" + ("" if len(files) == 1 else "s")))
    html = R.page("Music Wrapped", "Music Wrapped", "All your Wrapped",
                  "Every report you've generated, newest first", counts, "".join(sections),
                  "Rebuilt each time a report is generated. Open it with <b>music-wrapped home</b>.")
    paths.REPORTS.mkdir(parents=True, exist_ok=True)
    (paths.REPORTS / "index.html").write_text(html, encoding="utf-8")


def latest(kind=None):
    if kind:
        p = paths.REPORTS / kind / "latest.html"
        return p if p.exists() else None
    found = [p for k in paths.REPORT_KINDS for p in [paths.REPORTS / k / "latest.html"] if p.exists()]
    return max(found, key=lambda p: p.stat().st_mtime) if found else None
