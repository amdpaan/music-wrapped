"""Shareable story cards: 1080x1920 PNGs (Instagram / WhatsApp story size), Wrapped style.

Each card is a small HTML page (same texture, mascot and covers as the reports) rendered to PNG
by renderer/main.swift with the system WebKit.
"""

import calendar
import shutil
import subprocess
import tempfile
from datetime import date, timedelta
from pathlib import Path

from . import artwork, paths, render as R, stats as S
from .reports import fmt_range, month_bounds, week_of

W, H = 1080, 1920
COVER = 640  # px; cached separately from the report covers (160 px)
REPO = Path(__file__).resolve().parent.parent

CSS = """
*{box-sizing:border-box;margin:0;padding:0}
html,body{width:1080px;height:1920px;overflow:hidden}
body{background:#09090d;color:#f4f4f6;font-family:-apple-system,BlinkMacSystemFont,"SF Pro Display","Helvetica Neue",Arial,sans-serif;
  -webkit-font-smoothing:antialiased}
#bg{position:fixed;inset:0;width:100%;height:100%;z-index:0}
.page{position:relative;z-index:1;height:1920px;padding:96px 72px 80px;display:flex;flex-direction:column}
.top{display:flex;align-items:center;gap:22px;margin-bottom:56px}
.top .mascot{width:112px;height:70px}
.top .mascot svg{width:100%;height:100%;shape-rendering:crispEdges}
.top b{font-size:30px;font-weight:900;letter-spacing:.16em;text-transform:uppercase}
.top span{display:block;font-size:26px;font-weight:600;opacity:.65;letter-spacing:0;text-transform:none;margin-top:2px}
.panel{flex:1;border-radius:56px;padding:72px 64px;display:flex;flex-direction:column;overflow:hidden;position:relative}
.kicker{font-size:34px;font-weight:900;letter-spacing:.14em;text-transform:uppercase;opacity:.85;margin-bottom:28px}
.huge{font-size:300px;font-weight:900;letter-spacing:-.05em;line-height:.9}
.big{font-weight:900;letter-spacing:-.035em;line-height:1.02;overflow-wrap:anywhere;
  display:-webkit-box;-webkit-line-clamp:3;-webkit-box-orient:vertical;overflow:hidden}
.mid{font-size:48px;font-weight:800;opacity:.85;margin-top:22px}
.small{font-size:36px;font-weight:700;opacity:.75;margin-top:14px}
.grow{flex:1}
.art{display:flex;align-items:center;justify-content:center;background:rgba(0,0,0,.25) center/cover no-repeat;
  font-weight:900;color:inherit;box-shadow:0 24px 60px rgba(0,0,0,.35);flex:none}
.cover{width:760px;height:760px;border-radius:28px;font-size:300px;align-self:center;margin:24px 0 56px}
.round{border-radius:50%}
.artist{width:680px;height:680px;font-size:300px;align-self:center;margin:24px 0 56px}
ol{list-style:none;display:flex;flex-direction:column;gap:44px;margin-top:36px}
li{display:flex;align-items:center;gap:30px}
li .n{font-size:64px;font-weight:900;width:56px;text-align:right;opacity:.8;flex:none}
li .art{width:184px;height:184px;border-radius:18px;font-size:76px;box-shadow:0 10px 24px rgba(0,0,0,.3)}
li .t{min-width:0;flex:1}
li .t b{display:block;font-size:56px;font-weight:900;line-height:1.1;white-space:nowrap;overflow:hidden;text-overflow:ellipsis}
li .t span{display:block;font-size:38px;font-weight:600;opacity:.75;white-space:nowrap;overflow:hidden;text-overflow:ellipsis;margin-top:4px}
li .v{font-size:36px;font-weight:800;white-space:nowrap}
.bars{display:flex;flex-direction:column;gap:64px;margin-top:72px}
.bar b{display:flex;justify-content:space-between;font-size:48px;font-weight:800;margin-bottom:16px}
.bar .tr{height:36px;border-radius:0 8px 8px 0;background:rgba(255,255,255,.08);overflow:hidden}
.bar .tr i{display:block;height:100%;background:#1ed760;border-radius:0 8px 8px 0}
.cols{display:grid;grid-template-columns:minmax(0,1fr) minmax(0,1fr);gap:48px;margin-top:64px}
.cols > div{min-width:0}
.cols h3{font-size:34px;font-weight:900;letter-spacing:.08em;text-transform:uppercase;opacity:.75;margin-bottom:18px}
.cols p{font-size:46px;font-weight:800;line-height:1.75;white-space:nowrap;overflow:hidden;text-overflow:ellipsis}
.cols p em{font-style:normal;opacity:.6;margin-right:12px}
.foot{margin-top:48px;font-size:28px;font-weight:700;opacity:.55;display:flex;justify-content:space-between}
.hero{background:radial-gradient(120% 140% at 0% 0%,#ff4fa3 0%,transparent 55%),
  radial-gradient(120% 140% at 100% 100%,#1ed760 0%,transparent 50%),linear-gradient(135deg,#5b21d6,#2f6bff);color:#fff}
.hero .mascot-big{width:384px;height:240px;margin:8px 0 60px}
.hero .mascot-big svg{width:100%;height:100%;shape-rendering:crispEdges;filter:drop-shadow(0 16px 30px rgba(0,0,0,.35))}
"""


def _size_for(text, sizes=((12, 132), (20, 112), (32, 92), (48, 76))):
    n = len(text)
    for limit, px in sizes:
        if n <= limit:
            return px
    return 64


def _page(top_label, inner, foot):
    return f"""<!doctype html><html><head><meta charset="utf-8"><style>{CSS}</style></head>
<body><canvas id="bg"></canvas><div class="page">
<div class="top"><div class="mascot">{R.MASCOT}</div><div><b>Music Wrapped</b><span>{R.e(top_label)}</span></div></div>
{inner}
<div class="foot"><span>{R.e(foot)}</span><span>made with music-wrapped</span></div>
</div>{R.BG_JS}</body></html>"""


def _cover(pid, name, cls, style=""):
    html = R.cover(pid, name).replace('class="art', f'class="art {cls}', 1)
    return html.replace("<span ", f'<span style="{style}" ', 1) if style else html


def _panel(theme, body):
    if theme == "hero":
        return f'<div class="panel hero">{body}</div>'
    bg, ink = R.THEMES[theme]
    return f'<div class="panel" style="background:{bg};color:{ink}">{body}</div>'


def collect(con, kind, start=None, end=None):
    """Numbers for the cards: dict, or None if there's nothing to show."""
    if kind == "alltime":
        lib = S.library_totals(con)
        if not lib["plays"]:
            return None
        genres = S.library_top(con, "genres", 5)
        return {"minutes": round(lib["hours"] * 60), "plays": lib["plays"], "artists": lib["artists"],
                "songs": S.library_top(con, "songs", 5), "top_artists": S.library_top(con, "artists", 5),
                "genres": genres, "genre_total": sum(r.plays for r in S.library_top(con, "genres", 10_000))}
    plays = S.plays_between(con, start, end)
    if not plays:
        return None
    return {"minutes": round(S.hours(plays) * 60), "plays": len(plays), "artists": len({p.artist for p in plays}),
            "songs": S.top_songs(plays, 5), "top_artists": S.top_artists(plays, 5),
            "genres": S.top_genres(plays, 5), "genre_total": sum(1 for p in plays if p.genre)}


def _huge(n, max_px=300, width=808):
    """Font size so a big number fits the panel width (digits are about 0.62 em wide)."""
    return min(max_px, int(width / (len(n) * 0.62)))


def cards(d, label, words, foot):
    """[(file name, html)] for the story."""
    out = []
    plural = lambda n, w: f"{n:,} {w}" + ("" if n == 1 else "s")

    out.append(("01-intro", _page(label, _panel("hero", f"""
<div class="kicker">{R.e(words["kicker"])}</div>
<div class="grow"></div>
<div class="mascot-big">{R.MASCOT}</div>
<div class="mid" style="opacity:.95">You listened for</div>
<div class="huge" style="font-size:{_huge(f"{d['minutes']:,}")}px">{d['minutes']:,}</div>
<div class="mid" style="font-size:72px;font-weight:900;opacity:1">minutes</div>
<div class="grow"></div>
<div class="small" style="font-size:42px">{plural(d['plays'], 'play')} · {plural(d['artists'], 'artist')}</div>"""), foot)))

    s = d["songs"][0]
    out.append(("02-top-song", _page(label, _panel("green", f"""
<div class="kicker">Your top song</div>
{_cover(s.pid, s.name, 'cover')}
<div class="big" style="font-size:{_size_for(s.name)}px">{R.e(s.name)}</div>
<div class="mid">{R.e(s.sub)}</div>
<div class="grow"></div>
<div class="small">{plural(s.plays, 'play')} · {round(s.seconds / 60):,} minutes</div>"""), foot)))

    a = d["top_artists"][0]
    out.append(("03-top-artist", _page(label, _panel("pink", f"""
<div class="kicker">Your top artist</div>
{_cover(a.pid, a.name, 'artist round')}
<div class="big" style="font-size:{_size_for(a.name)}px;text-align:center">{R.e(a.name)}</div>
<div class="grow"></div>
<div class="small" style="text-align:center">{plural(a.plays, 'play')} · {round(a.seconds / 60):,} minutes</div>"""), foot)))

    rows = "".join(f'<li><span class="n">{i}</span>{R.cover(r.pid, r.name)}<span class="t"><b>{R.e(r.name)}</b>'
                   f'<span>{R.e(r.sub)}</span></span><span class="v">{r.plays:,}</span></li>'
                   for i, r in enumerate(d["songs"], 1))
    out.append(("04-top-songs", _page(label, _panel("purple", f"""
<div class="kicker">Your top songs</div>
<ol>{rows}</ol>
<div class="grow"></div>
<div class="small">plays {R.e(words["span"])}</div>"""), foot)))

    if d["genres"]:
        g = d["genres"][0]
        total = d["genre_total"] or 1
        top = d["genres"][0].plays or 1
        bars = "".join(f'<div class="bar"><b><span>{R.e(r.name)}</span><span>{r.plays / total * 100:.0f}%</span></b>'
                       f'<div class="tr"><i style="width:{r.plays / top * 100:.1f}%"></i></div></div>'
                       for r in d["genres"])
        out.append(("05-top-genre", _page(label, _panel("dark", f"""
<div class="kicker">Your top genre</div>
<div class="big" style="font-size:{_size_for(g.name, ((10, 170), (16, 130), (24, 104)))}px;color:#1ed760">{R.e(g.name)}</div>
<div class="mid">{g.plays / total * 100:.0f}% of your plays</div>
<div class="bars">{bars}</div>
<div class="grow"></div>"""), foot)))

    artists = "".join(f"<p><em>{i}</em>{R.e(r.name)}</p>" for i, r in enumerate(d["top_artists"], 1))
    songs = "".join(f"<p><em>{i}</em>{R.e(r.name)}</p>" for i, r in enumerate(d["songs"], 1))
    genre = R.e(d["genres"][0].name) if d["genres"] else "—"
    out.append(("06-summary", _page(label, _panel("hero", f"""
<div class="kicker">{R.e(words["wrapped"])}</div>
<div style="display:flex;gap:48px;align-items:center">
  {_cover(a.pid, a.name, "round", "width:360px;height:360px;font-size:150px")}
  <div><div class="small" style="margin:0">Top artist</div>
  <div class="big" style="font-size:{min(_size_for(a.name), 88)}px">{R.e(a.name)}</div></div>
</div>
<div class="cols"><div><h3>Top artists</h3>{artists}</div><div><h3>Top songs</h3>{songs}</div></div>
<div class="grow"></div>
<div class="cols" style="margin-top:0"><div><h3>Minutes listened</h3><div class="huge" style="font-size:{_huge(f"{d['minutes']:,}", 120, 380)}px">{d['minutes']:,}</div></div>
<div><h3>Top genre</h3><div class="big" style="font-size:72px;-webkit-line-clamp:2">{genre}</div></div></div>"""), foot)))
    return out


def period(kind, a, today=None):
    """(name, label, words, start, end) for the story's period."""
    today = today or date.today()
    if kind == "weekly":
        from .reports import parse_week
        start, end = week_of(parse_week(a.week) if a.week else today)
        y, w, _ = start.isocalendar()
        words = {"kicker": "Your week in music", "span": "this week", "wrapped": "Your week, wrapped"}
        return f"{y}-W{w:02d}", f"Week {w} · {fmt_range(start, end)}", words, start, min(end, today + timedelta(days=1))
    if kind == "monthly":
        if a.month:
            y, m = map(int, a.month.split("-"))
        elif a.current:
            y, m = today.year, today.month
        else:
            last = today.replace(day=1) - timedelta(days=1)
            y, m = last.year, last.month
        start, end = month_bounds(y, m)
        mn = calendar.month_name[m]
        words = {"kicker": f"Your {mn} in music", "span": f"in {mn}", "wrapped": f"Your {mn}, wrapped"}
        return f"{y}-{m:02d}", f"{mn} {y}", words, start, min(end, today + timedelta(days=1))
    if kind == "yearly":
        y = a.year or today.year
        start, end = date(y, 1, 1), date(y, 12, 1)
        words = {"kicker": f"Your {y} in music", "span": f"in {y}", "wrapped": f"Your {y}, wrapped"}
        return str(y), f"{y} · January – November", words, start, min(end, today + timedelta(days=1))
    words = {"kicker": "Your all-time music", "span": "of all time", "wrapped": "All time, wrapped"}
    return today.isoformat(), "All time", words, None, None


def renderer():
    """Path to the compiled renderer, building it if it's missing or older than its source."""
    exe = paths.SUPPORT / "bin/music-wrapped-render"
    src = REPO / "renderer/main.swift"
    if not exe.exists() or exe.stat().st_mtime < src.stat().st_mtime:
        exe.parent.mkdir(parents=True, exist_ok=True)
        print("Building the story renderer (once)…")
        subprocess.run(["swiftc", "-O", "-o", str(exe), str(src)], check=True)
    return exe


def make(con, kind, a):
    """Renders the story PNGs. Returns the output folder, or None if there's no data."""
    name, label, words, start, end = period(kind, a)
    d = collect(con, kind, start, end)
    if not d:
        return None
    foot = "Apple Music · Mac + other devices"
    pages = cards(d, label, words, foot)
    out = paths.SUPPORT / "stories" / kind / name
    if out.exists():
        shutil.rmtree(out)
    out.mkdir(parents=True)
    with tempfile.TemporaryDirectory() as tmp:
        jobs = []
        for fname, html in pages:
            page = Path(tmp) / f"{fname}.html"
            page.write_text(artwork.inject(html, size=COVER), encoding="utf-8")
            jobs += [str(page), str(out / f"{fname}.png")]
        subprocess.run([str(renderer()), str(W), str(H), *jobs], check=True, timeout=300)
    return out
