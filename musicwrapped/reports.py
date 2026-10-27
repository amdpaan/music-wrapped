"""Builds and saves the weekly / monthly / yearly / all-time / custom reports."""

import calendar
import re
import shutil
from datetime import date, datetime, timedelta

from . import artwork, paths, render as R, slides as SL, stats as S

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
    mac = sum(1 for p in plays if p.source in S.LIVE)
    return mac, len(plays) - mac


def footer(con, extra=""):
    lt = S.logged_totals(con)
    since = f"Logging since <b>{lt['since']:%-d %b %Y}</b>. " if lt["since"] else "No plays logged yet. "
    return (since + "Top lists and hours include <b>all devices</b>: Mac plays are timed live; plays on other devices "
            "(e.g. iPhone) are inferred from synced play counts, so each one counts as the full song and its time "
            "is approximate. <b>≈</b> marks times that include those estimates. Heatmap and skips are <b>Mac only</b>. " + extra)


def top_cards(plays, n, theme_songs="green", theme_artists="pink", theme_albums="purple"):
    return (R.card(f"Top {n} songs", R.ranked(S.top_songs(plays, n)), theme_songs, badge=ALL_DEVICES)
            + R.card(f"Top {n} artists", R.ranked(S.top_artists(plays, n), round_=True), theme_artists, badge=ALL_DEVICES)
            + R.card(f"Top {n} albums", R.ranked(S.top_albums(plays, n)), theme_albums, badge=ALL_DEVICES))


def genres_card(plays, n):
    rows = S.top_genres(plays, n)
    known = sum(1 for p in plays if p.genre)
    return R.card(f"Top {len(rows) or n} genres", R.genre_bars(rows, known), "dark", badge=ALL_DEVICES, wide=True,
                  note="Share of plays with a known genre; covers show each genre's most-played song")


def records_cards(plays):
    """Longest session (Mac only) and the song replayed most in one day."""
    out = ""
    session = S.longest_session(plays)
    if session:
        start, end, n = session
        out += R.card("Longest session", R.headline(SL.duration(start, end),
                      f"{start:%a %-d %b}, {start:%H:%M}–{end:%H:%M} · {SL.plural(n, 'song')}"), "teal",
                      note="Back-to-back listening; breaks under 10 minutes don't end it", badge=MAC_ONLY)
    replay = S.most_replayed_day(plays)
    if replay:
        r, day = replay
        out += R.card("Most replayed in a day", R.headline(r.name, f"{r.sub} · {r.plays} plays on {day:%a %-d %b}", r.pid, art=True),
                      "pink", note="The same song, the most times in one day", badge=ALL_DEVICES)
    return out


def personality_for(con, plays, start, end):
    days = max(1, (min(end, date.today() + timedelta(days=1)) - start).days)
    return S.personality(plays, len(S.new_artists(con, plays, start, 10_000)), days)


def personality_card(p):
    if not p:
        return ""
    name, desc, traits = p
    return R.card("Listening personality", R.headline(name, desc + (f" Also: {', '.join(traits)}." if traits else "")),
                  "orange", note="From the habits that stood out most", badge=ALL_DEVICES)


def _records_slide(plays):
    return ("records", SL.records(S.longest_session(plays), S.most_replayed_day(plays)))


def hero_stats(plays, compare=None):
    mac, other = device_split(plays)
    h, est = S.hours(plays), S.estimated_hours(plays)
    note = f" · ≈{R.fmt_hours(est)} estimated" if est else ""
    st = [(f"hours listened{note}", f"{h:,.1f}") if h >= 1 else (f"listened{note}", R.fmt_hours(h)),
          ("plays", f"{len(plays):,}"),
          ("artists", f"{len({p.artist for p in plays}):,}")]
    if compare:
        st.append(compare)
    st.append(("plays on this Mac", f"{mac:,}"))
    st.append(("plays on other devices", f"{other:,}"))
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

def _prev_same_point(prev, start, prev_start, end):
    """For a period still in progress: the previous period's plays up to the same point (e.g. Monday
    to Wednesday 15:00 of last week), so the comparison is like for like. None if the period is over."""
    now = datetime.now()
    if now >= datetime(end.year, end.month, end.day):
        return None
    cut = S.ts_of(prev_start) + (int(now.timestamp()) - S.ts_of(start))
    return [p for p in prev if p.ts < cut]


def _story(slides_list):
    return "".join(h for _, h in slides_list)


def weekly(con, week_start, slides_only=False):
    start, end = week_of(week_start)
    y, w, _ = start.isocalendar()
    name = f"{y}-W{w:02d}"
    plays = S.plays_between(con, start, end)
    prev = S.plays_between(con, start - timedelta(days=7), start)
    so_far = _prev_same_point(prev, start, start - timedelta(days=7), end)
    cmp_label = "this time last week" if so_far is not None else "last week"
    h, ph = S.hours(plays), S.hours(prev)
    pc = ph if so_far is None else S.hours(so_far)

    repeat = [(r.name, r.sub, R.fmt_plays(r.plays)) for r in S.on_repeat(plays, 5)]
    skipped = [(t, a, f"{s} of {n} skipped") for t, a, s, n in S.most_skipped(plays)]
    new_rows = S.new_artists(con, plays, start)
    new = [(r.name, "first time this week", R.fmt_plays(r.plays)) for r in new_rows]
    body = (top_cards(plays, 5)
            + genres_card(plays, 5)
            + R.card("When you listened", R.heatmap(S.heatmap(plays)), "dark",
                     note="Minutes per hour, Monday to Sunday", badge=MAC_ONLY, wide=True)
            + R.card("On repeat", R.simple_list(repeat, "No song hit 5 plays this week."), "orange",
                     note="Songs with 5+ plays", badge=ALL_DEVICES)
            + R.card("Most skipped", R.simple_list(skipped, "No skips logged. Every song earned its spot."), "blue",
                     note="Stopped before the halfway mark", badge=MAC_ONLY)
            + R.card("New artists", R.simple_list(new, "No new artists this week."), "yellow",
                     note="Artists you hadn't played before", badge=ALL_DEVICES)
            + records_cards(plays))
    label = f"Week {w} · {fmt_range(start, end)}"
    d = SL.data_for(con, "weekly", plays, prev if so_far is None else so_far, start, end)
    if d:
        d["prev_label"] = cmp_label
    last_day = min(end, date.today() + timedelta(days=1)) - timedelta(days=1)
    sl = SL.build(d, SL.words("weekly"), label, [
        ("peak", SL.peak(d, None)),
        ("changes", SL.changes(d, SL.words("weekly"), prev, S.streak_until(con, last_day), len(new_rows))),
        _records_slide(plays),
    ]) if d else []
    if slides_only:
        return "weekly", name, sl
    stats = hero_stats(plays, (f"vs {cmp_label}", _pct(h, pc)))
    html = R.page(f"Wrapped {name}", f"Your week in music · {name}", "Your Week, Wrapped",
                  fmt_range(start, end), stats, body,
                  footer(con, f"Last week: <b>{R.fmt_hours(ph)}</b>."), live=date.today() < end,
                  story=_story(sl), story_css=SL.CSS, story_js=SL.JS)
    return "weekly", name, html


def _pct(h, ph):
    if ph <= 0:
        return "–"
    pct = (h - ph) / ph * 100
    return f"{'+' if pct >= 0 else ''}{pct:.0f}%"


def monthly(con, y, m, so_far=False, slides_only=False):
    start, end = month_bounds(y, m)
    q_end = clip_now(end) if so_far else end
    name = f"{y}-{m:02d}"
    plays = S.plays_between(con, start, q_end)
    ps, pe = month_bounds(y - (m == 1), (m - 2) % 12 + 1)
    prev = S.plays_between(con, ps, pe)
    part = _prev_same_point(prev, start, ps, end) if so_far else None
    cmp_label = "this time last month" if part is not None else "last month"
    pc = S.hours(prev if part is None else part)
    title = f"{calendar.month_name[m]} {y}"
    d = SL.data_for(con, "monthly", plays, prev if part is None else part, start, q_end)
    if d:
        d["prev_label"] = cmp_label
    weeks = [(lab, h) for lab, h, _ in week_bars(plays, start, q_end)]
    persona = personality_for(con, plays, start, q_end)
    wd = SL.words("monthly", calendar.month_name[m])
    sl = SL.build(d, wd, fmt_range(start, q_end), [
        ("best-week", SL.best_bucket("Your biggest week", weeks, lambda l: f"Week {int(l[1:])}")),
        ("changes", SL.changes(d, wd, prev, S.streak_until(con, q_end - timedelta(days=1)),
                               len(S.new_artists(con, plays, start)))),
        ("personality", SL.personality(persona)),
        _records_slide(plays),
    ]) if d else []
    if slides_only:
        return "monthly", name, sl
    body = (top_cards(plays, 10)
            + genres_card(plays, 5)
            + R.card("Hours per week", R.bars(week_bars(plays, start, q_end)), "dark",
                     note="Listening hours in each week of the month (weeks start Monday)", badge=ALL_DEVICES, wide=True)
            + R.card("How your top artists moved", artist_changes(plays, start, q_end), "dark",
                     note="Your month's top 5 artists, ranked week by week", badge=ALL_DEVICES, wide=True)
            + personality_card(persona)
            + records_cards(plays))
    html = R.page(f"Wrapped {title}", "Your month in music" + (" · so far" if so_far else ""), title,
                  fmt_range(start, q_end), hero_stats(plays, (f"vs {cmp_label}", _pct(S.hours(plays), pc))), body,
                  footer(con), story=_story(sl), story_css=SL.CSS, story_js=SL.JS)
    return "monthly", name, html


def yearly(con, y, slides_only=False):
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

    d = SL.data_for(con, "yearly", plays, None, start, q_end)
    persona = personality_for(con, plays, start, q_end)
    days_total = max(1, (q_end - start).days)
    sl = SL.build(d, SL.words("yearly", str(y)), fmt_range(start, q_end), [
        ("top-artists", SL.ranked_list("Your top artists", S.top_artists(plays, 5), "pink", f"plays in {y}", round_=True)),
        ("top-albums", SL.ranked_list("Your top albums", S.top_albums(plays, 5), "blue", f"plays in {y}")),
        ("days", SL.days_slide(len({p.dt.date() for p in plays}), days_total, S.first_play(plays), y)),
        ("streak", SL.streak(streak, s_from, s_to)),
        ("discovery", SL.discovery(disc[0] if disc else None)),
        ("months", SL.months_grid(month_items)),
        ("best-month", SL.best_bucket("Your biggest month", [(m, h) for m, h, _ in month_hours],
                                      lambda m: calendar.month_name[list(calendar.month_abbr).index(m)])),
        ("personality", SL.personality(persona)),
        _records_slide(plays),
    ]) if d else []
    if slides_only:
        return "yearly", str(y), sl
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
            + genres_card(plays, 5)
            + R.card("Top song of each month", R.months(month_items), "blue", badge=ALL_DEVICES, wide=True)
            + R.card("Hours per month", R.bars(month_hours), "dark", badge=ALL_DEVICES, wide=True)
            + personality_card(persona)
            + records_cards(plays))
    html = R.page(f"Wrapped {y}", f"{y} Wrapped · January to November", f"Your {y}, Wrapped",
                  fmt_range(start, q_end), hero_stats(plays), body, footer(con),
                  story=_story(sl), story_css=SL.CSS, story_js=SL.JS)
    return "yearly", str(y), html


def alltime(con, slides_only=False):
    every = S.alltime_songs(con)
    lib = S.library_totals(con, every)
    lt = S.logged_totals(con)
    songs = S.library_top(con, "songs", 25, every)
    artists = S.library_top(con, "artists", 25, every)
    albums = S.library_top(con, "albums", 25, every)
    genres = S.library_top(con, "genres", 10, every)
    d = SL.data_for(con, "alltime")
    sl = SL.build(d, SL.words("alltime"), f"{lib['tracks']:,} songs in your library") if d else []
    if slides_only:
        return "alltime", date.today().isoformat(), sl
    body = (R.card("Top 25 songs", R.ranked(songs, "Run a backfill first."), "green")
            + R.card("Top 25 artists", R.ranked(artists, "Run a backfill first.", round_=True), "pink")
            + R.card("Top 25 albums", R.ranked(albums, "Run a backfill first."), "purple")
            + R.card(f"Top {len(genres) or 10} genres", R.genre_bars(genres, sum(r.plays for r in S.library_top(con, "genres", 10_000, every))),
                     "dark", wide=True, note="By play count; covers show each genre's most-played song"))
    stats = [("all-time plays", f"{lib['plays']:,}"),
             ("est. hours", f"{lib['hours']:,.0f}"),
             ("hours logged", f"{lt['hours']:,.1f}"),
             ("plays logged", f"{lt['plays']:,}"),
             ("artists", f"{lib['artists']:,}")]
    note = ("All-time rankings use your Music library's play counts (every device, since you added each song); "
            "hours there are estimated as plays × track length. ")
    if lib["yt_plays"]:
        note += (f"They also include {lib['yt_plays']:,} YT Music play{'s' if lib['yt_plays'] != 1 else ''} logged on this Mac, "
                 "timed live; YT Music has no genres, so those count toward a genre only when the song is also in your library. ")
    if lib["yt_history"]:
        note += (f"Plus {lib['yt_history']:,} plays from your imported YT Music history (Google Takeout, every device): "
                 "YouTube lists a song as soon as it starts, so skips count too, and their time is each song's length. ")
    html = R.page("Wrapped All Time", "All time", "Your All-Time, Wrapped",
                  f"{lib['tracks']:,} tracks in your library", stats, body, footer(con, note),
                  story=_story(sl), story_css=SL.CSS, story_js=SL.JS)
    return "alltime", date.today().isoformat(), html


def custom(con, start, end_incl, label=None, slides_only=False):
    end = end_incl + timedelta(days=1)
    plays = S.plays_between(con, start, end)
    streak, s_from, s_to = S.longest_streak(plays)
    repeat = [(r.name, r.sub, R.fmt_plays(r.plays)) for r in S.on_repeat(plays, 5)[:10]]
    skipped = [(t, a, f"{s} of {n} skipped") for t, a, s, n in S.most_skipped(plays)]
    new = [(r.name, "new in this period", R.fmt_plays(r.plays)) for r in S.new_artists(con, plays, start)]
    persona = personality_for(con, plays, start, end)
    body = (top_cards(plays, 10)
            + genres_card(plays, 5)
            + R.card("Hours per week", R.bars(week_bars(plays, start, end)), "dark", badge=ALL_DEVICES, wide=True)
            + R.card("When you listened", R.heatmap(S.heatmap(plays)), "dark",
                     note="Minutes per hour, Monday to Sunday", badge=MAC_ONLY, wide=True)
            + R.card("Longest streak", R.headline(f"{streak} day" + ("" if streak == 1 else "s"),
                     f"{s_from:%-d %b} – {s_to:%-d %b}" if streak else "No plays logged"), "orange")
            + R.card("New artists", R.simple_list(new, "No new artists in this period."), "yellow", badge=ALL_DEVICES)
            + R.card("On repeat", R.simple_list(repeat, "No song hit 5 plays."), "teal", note="Songs with 5+ plays")
            + R.card("Most skipped", R.simple_list(skipped, "No skips logged."), "blue", badge=MAC_ONLY)
            + personality_card(persona)
            + records_cards(plays))
    slug = re.sub(r"[^a-z0-9]+", "-", label.lower()).strip("-") if label else ""
    name = f"{start}_to_{end_incl}" + (f"_{slug}" if slug else "")
    d = SL.data_for(con, "custom", plays, None, start, end)
    weeks = [(lab, h) for lab, h, _ in week_bars(plays, start, end)]
    sl = SL.build(d, SL.words("custom", label), fmt_range(start, end), [
        ("peak", SL.peak(d, None)),
        ("streak", SL.streak(streak, s_from, s_to)),
        ("best-week", SL.best_bucket("Your biggest week", weeks, lambda l: f"Week {int(l[1:])}")),
        ("personality", SL.personality(persona)),
        _records_slide(plays),
    ]) if d else []
    if slides_only:
        return "custom", name, sl
    html = R.page(f"Wrapped {label or name}", "Custom Wrapped", label or "Your Wrapped",
                  fmt_range(start, end), hero_stats(plays), body, footer(con),
                  story=_story(sl), story_css=SL.CSS, story_js=SL.JS)
    return "custom", name, html


# ---------- output ----------

def save(kind, name, html):
    folder = paths.REPORTS / kind
    folder.mkdir(parents=True, exist_ok=True)
    out = folder / f"{name}.html"
    if kind in ("weekly", "monthly", "yearly", "alltime"):
        # Shown only when opened through `music-wrapped serve`, which makes the images on demand.
        html = html.replace("<!--story-images-->", (
            f'<a class="story-link" hidden href="../../stories/{kind}/{name}/">Story images ↗</a>'
            '<script>if (/^https?:/.test(location.protocol)) document.querySelector(".story-link").hidden = false</script>'), 1)
    html, version = R.stamp_live(html, f"{name}.version.js")
    out.write_text(artwork.inject(html), encoding="utf-8")
    shutil.copyfile(out, folder / "latest.html")
    if "__mwVersion" in html:   # a live page: tell open tabs it changed (after the page itself is written)
        (folder / f"{name}.version.js").write_text(version, encoding="utf-8")
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
    feature = ""
    try:
        from . import db
        con = db.connect()
        start, end = week_of(date.today())
        d = SL.data_for(con, "weekly", S.plays_between(con, start, end), None, start, end)
        buttons = [(f"{k}/latest.html{h}", t) for k, h, t in (("weekly", "", "Open this week →"),
                                                              ("weekly", "#play", "▶ Play story"),
                                                              ("yearly", "", "This year"), ("monthly", "", "Latest month"),
                                                              ("alltime", "", "All time"))
                   if (paths.REPORTS / k / "latest.html").exists()]
        feature = R.feature(d, buttons)
        con.close()
    except Exception as ex:  # the list of reports matters more than the header
        print(f"home page header skipped: {ex}")
    html = R.page("Music Wrapped", "Music Wrapped", "All your Wrapped",
                  "Every report you've generated, newest first", [], feature + "".join(sections),
                  "Rebuilt with every play and report. Open it with <b>music-wrapped home</b>.", home=True, live=True)
    paths.REPORTS.mkdir(parents=True, exist_ok=True)
    html, version = R.stamp_live(html, "index.version.js")
    (paths.REPORTS / "index.html").write_text(artwork.inject(html), encoding="utf-8")
    (paths.REPORTS / "index.version.js").write_text(version, encoding="utf-8")


def latest(kind=None):
    if kind:
        p = paths.REPORTS / kind / "latest.html"
        return p if p.exists() else None
    found = [p for k in paths.REPORT_KINDS for p in [paths.REPORTS / k / "latest.html"] if p.exists()]
    return max(found, key=lambda p: p.stat().st_mtime) if found else None
