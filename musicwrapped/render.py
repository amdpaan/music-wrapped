"""Self-contained Wrapped-style HTML (no external fonts, scripts or images)."""

from datetime import datetime
from html import escape

# Card themes: (background, ink). Bold, saturated, Wrapped-like.
THEMES = {
    "green": ("#1ed760", "#08130c"),
    "pink": ("#ff4fa3", "#1d0010"),
    "purple": ("#7b3fe4", "#ffffff"),
    "orange": ("#ff7a1a", "#1d0a00"),
    "blue": ("#2f6bff", "#ffffff"),
    "yellow": ("#f4e04d", "#171300"),
    "teal": ("#19c3b1", "#001a17"),
    "lilac": ("#c9b8ff", "#160b3a"),
    "red": ("#ff4545", "#ffffff"),
    "dark": ("#17171f", "#f4f4f6"),
}

CSS = """
*{box-sizing:border-box;margin:0;padding:0}
:root{color-scheme:dark;--bg:#09090d;--ink:#f4f4f6;--muted:#9a9aa8;--line:#2a2a35;--cell:#23232d}
body{background:var(--bg);color:var(--ink);font:16px/1.4 -apple-system,BlinkMacSystemFont,"SF Pro Display","Helvetica Neue",Arial,sans-serif;
  -webkit-font-smoothing:antialiased;padding:32px 16px 64px}
main{max-width:1180px;margin:0 auto}
.hero{border-radius:28px;padding:44px 36px;margin-bottom:20px;color:#fff;position:relative;overflow:hidden;
  background:radial-gradient(120% 140% at 0% 0%,#ff4fa3 0%,transparent 55%),radial-gradient(120% 140% at 100% 100%,#1ed760 0%,transparent 50%),
  linear-gradient(135deg,#5b21d6,#2f6bff)}
.hero .kicker{font-weight:800;letter-spacing:.14em;text-transform:uppercase;font-size:13px;opacity:.9}
.hero h1{font-size:clamp(40px,8vw,88px);line-height:.95;font-weight:900;letter-spacing:-.035em;margin:12px 0 10px}
.hero .range{font-size:18px;font-weight:600;opacity:.92}
.stats{display:flex;flex-wrap:wrap;gap:12px;margin-top:28px}
.stat{background:rgba(0,0,0,.28);border-radius:18px;padding:14px 18px;min-width:150px}
.stat b{display:block;font-size:34px;font-weight:900;letter-spacing:-.02em;line-height:1.05}
.stat span{font-size:13px;font-weight:600;opacity:.85}
.grid{display:grid;grid-template-columns:repeat(auto-fit,minmax(320px,1fr));gap:20px}
.card{border-radius:24px;padding:26px 24px;min-width:0}
.card.wide{grid-column:1/-1}
.card h2{font-size:26px;font-weight:900;letter-spacing:-.02em;line-height:1.05;margin-bottom:4px}
.card .note{font-size:13px;font-weight:600;opacity:.75;margin-bottom:16px}
.pill{display:inline-block;font-size:11px;font-weight:800;letter-spacing:.08em;text-transform:uppercase;
  border:1.5px solid currentColor;border-radius:999px;padding:2px 8px;margin-left:8px;vertical-align:middle;opacity:.85}
ol.rank{list-style:none}
ol.rank li{display:flex;align-items:center;gap:14px;padding:9px 0;border-top:1px solid rgba(127,127,127,.25)}
ol.rank li:first-child{border-top:0}
ol.rank .n{font-weight:900;font-size:20px;width:30px;flex:none;opacity:.7}
ol.rank .t{min-width:0;flex:1}
ol.rank .t b{display:block;font-weight:800;white-space:nowrap;overflow:hidden;text-overflow:ellipsis}
ol.rank .t span{display:block;font-size:13px;opacity:.75;white-space:nowrap;overflow:hidden;text-overflow:ellipsis}
ol.rank .v{font-weight:800;font-size:14px;white-space:nowrap;text-align:right}
ol.rank .v small{display:block;font-weight:600;font-size:11px;opacity:.7}
ol.rank a{color:inherit;text-decoration:none;display:flex;align-items:center;gap:14px;flex:1;min-width:0;border-radius:10px}
ol.rank a:hover .t b{text-decoration:underline}
.art{flex:none;width:44px;height:44px;border-radius:6px;background:rgba(0,0,0,.22) center/cover no-repeat;
  display:flex;align-items:center;justify-content:center;font-weight:900;font-size:18px;overflow:hidden;box-shadow:0 2px 8px rgba(0,0,0,.18)}
.art.round{border-radius:50%}
li.first .art{width:72px;height:72px;font-size:28px;border-radius:8px}
li.first .art.round{border-radius:50%}
.hl{display:flex;gap:18px;align-items:center}
.hl .art{width:104px;height:104px;font-size:40px;border-radius:10px}
.hl .art.round{border-radius:50%}
.hl > div{min-width:0;flex:1}
.hl .big{font-size:clamp(26px,3vw,40px);overflow-wrap:anywhere;
  display:-webkit-box;-webkit-line-clamp:3;-webkit-box-orient:vertical;overflow:hidden}
.month{display:flex;gap:10px;align-items:center}
.month .art{width:40px;height:40px;font-size:16px}
.month > div{min-width:0}
ol.rank li.first .n{font-size:34px;opacity:1}
ol.rank li.first .t b{font-size:24px;letter-spacing:-.01em;white-space:normal;line-height:1.15;
  display:-webkit-box;-webkit-line-clamp:2;-webkit-box-orient:vertical;overflow-wrap:anywhere}
.empty{font-weight:700;opacity:.7;padding:8px 0}
.big{font-size:clamp(34px,5vw,54px);font-weight:900;letter-spacing:-.03em;line-height:1}
.sub{font-weight:700;opacity:.8;margin-top:8px}
/* charts */
.chart{position:relative}
[data-tip]{position:relative}
[data-tip]:hover::after{content:attr(data-tip);position:absolute;z-index:5;bottom:calc(100% + 6px);left:50%;transform:translateX(-50%);
  background:#fff;color:#111;font-size:12px;font-weight:700;padding:5px 8px;border-radius:8px;white-space:nowrap;pointer-events:none;
  box-shadow:0 4px 14px rgba(0,0,0,.4)}
.heat{display:grid;grid-template-columns:38px repeat(24,minmax(0,1fr));gap:3px;font-size:11px;color:var(--muted)}
.heat .c{aspect-ratio:1;border-radius:4px;background:var(--cell);min-height:10px}
.heat .c:hover{outline:2px solid #fff;outline-offset:1px}
.heat .rl{align-self:center;font-weight:700}
.heat .hl{text-align:center;font-weight:600}
.legend{display:flex;align-items:center;gap:4px;margin-top:12px;font-size:12px;color:var(--muted);font-weight:600}
.legend i{width:14px;height:14px;border-radius:3px;display:inline-block}
.bars{display:flex;align-items:flex-end;gap:10px;height:220px;padding-top:24px;border-bottom:1px solid var(--line)}
.bars .b{flex:1;display:flex;flex-direction:column;justify-content:flex-end;align-items:center;height:100%;min-width:0}
.bars .b i{display:block;width:100%;max-width:56px;background:#1ed760;border-radius:4px 4px 0 0;min-height:2px}
.bars .b:hover i{background:#6ff09c}
.bars .b em{font-style:normal;font-weight:800;font-size:13px;margin-bottom:6px}
.blabels{display:flex;gap:10px;margin-top:8px}
.blabels span{flex:1;text-align:center;font-size:12px;font-weight:700;color:var(--muted);min-width:0}
table.rg{width:100%;border-collapse:separate;border-spacing:3px;font-size:13px}
table.rg th{font-weight:700;color:var(--muted);text-align:center;padding:2px 4px}
table.rg th.a{text-align:left;color:var(--ink);font-weight:800;max-width:180px;overflow:hidden;text-overflow:ellipsis;white-space:nowrap}
table.rg td{text-align:center;border-radius:6px;padding:8px 4px;font-weight:800;background:var(--cell)}
details{margin-top:14px;font-size:13px;color:var(--muted)}
details summary{cursor:pointer;font-weight:700}
details table{border-collapse:collapse;margin-top:8px;font-size:12px}
details td,details th{padding:2px 8px;border-bottom:1px solid var(--line);text-align:right}
.months{display:grid;grid-template-columns:repeat(auto-fill,minmax(200px,1fr));gap:10px}
.month{background:rgba(0,0,0,.22);border-radius:14px;padding:12px 14px;min-width:0}
.month small{font-weight:900;letter-spacing:.1em;text-transform:uppercase;font-size:11px;opacity:.8}
.month b{display:block;font-weight:800;white-space:nowrap;overflow:hidden;text-overflow:ellipsis;margin-top:2px}
.month span{display:block;font-size:12px;opacity:.75;white-space:nowrap;overflow:hidden;text-overflow:ellipsis}
footer{margin-top:28px;color:var(--muted);font-size:13px;line-height:1.6}
footer b{color:var(--ink)}
@media (max-width:560px){.hero{padding:32px 22px}.card{padding:22px 18px}.heat{grid-template-columns:30px repeat(24,minmax(0,1fr));gap:2px}
  .heat .hl{font-size:9px}}
"""

# Sequential ramp (one hue, green) on the dark card surface: low -> high.
RAMP = ["#123d24", "#17603a", "#1b8a4f", "#1fb663", "#1ed760", "#8af5b2"]


def e(s):
    return escape(str(s if s is not None else ""))


def fmt_hours(h):
    if h < 1:
        return f"{round(h * 60)} min"
    return f"{h:.1f} h" if h < 100 else f"{h:,.0f} h"


def fmt_plays(n):
    return f"{n:,} play" + ("" if n == 1 else "s")


# Reloads the page every minute while it's visible, keeping the scroll position. Used for a
# week in progress, whose file the logger rebuilds after every play.
LIVE_JS = """<script>
(function () {
  var KEY = "mw-scroll:" + location.pathname;
  try {
    var y = sessionStorage.getItem(KEY);
    if (y !== null) { window.scrollTo(0, +y); sessionStorage.removeItem(KEY); }
  } catch (e) {}
  setInterval(function () {
    if (document.hidden || document.querySelector("details[open]")) return;
    try { sessionStorage.setItem(KEY, String(window.scrollY)); } catch (e) {}
    location.reload();
  }, 60000);
})();
</script>"""


def page(title, kicker, heading, range_label, stats, body, footer, live=False):
    tiles = "".join(f'<div class="stat"><b>{e(v)}</b><span>{e(k)}</span></div>' for k, v in stats)
    if live:
        kicker = f"{kicker} · live"
        footer = f"{footer} This page updates after every play and refreshes itself every minute.".strip()
    return f"""<!doctype html>
<html lang="en"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<meta name="color-scheme" content="dark">
<title>{e(title)}</title>
<style>{CSS}</style></head>
<body><main>
<section class="hero"><div class="kicker">{e(kicker)}</div><h1>{e(heading)}</h1>
<div class="range">{e(range_label)}</div><div class="stats">{tiles}</div></section>
<div class="grid">{body}</div>
<footer>{footer}<br>Generated {e(datetime.now().strftime("%a %-d %b %Y, %H:%M"))} · music-wrapped</footer>
</main>{LIVE_JS if live else ""}</body></html>
"""


def card(title, inner, theme="dark", note="", badge="", wide=False):
    bg, ink = THEMES[theme]
    pill = f'<span class="pill">{e(badge)}</span>' if badge else ""
    note_html = f'<div class="note">{e(note)}</div>' if note else '<div class="note"></div>'
    return (f'<section class="card{" wide" if wide else ""}" style="background:{bg};color:{ink}">'
            f"<h2>{e(title)}{pill}</h2>{note_html}{inner}</section>")


def cover(pid, name, round_=False):
    """Artwork slot. artwork.inject() fills `a-<PID>` with the image; otherwise the first letter shows."""
    cls = "art round" if round_ else "art"
    if pid:
        cls += f" a-{pid}"
    letter = (str(name).strip()[:1] or "♪").upper()
    return f'<span class="{cls}" aria-hidden="true">{e(letter)}</span>'


def ranked(rows, empty="Nothing here yet.", hours=True, round_=False):
    """rows: stats.Row(name, sub, plays, seconds, pid). round_: circular covers (artists)."""
    if not rows:
        return f'<div class="empty">{e(empty)}</div>'
    items = []
    for i, r in enumerate(rows, 1):
        sub = f"<span>{e(r.sub)}</span>" if r.sub else ""
        small = f"<small>{e(fmt_hours(r.seconds / 3600))}</small>" if hours and r.seconds else ""
        items.append(f'<li class="{"first" if i == 1 else ""}"><span class="n">{i}</span>{cover(r.pid, r.name, round_)}'
                     f'<span class="t"><b>{e(r.name)}</b>{sub}</span>'
                     f'<span class="v">{e(fmt_plays(r.plays))}{small}</span></li>')
    return f'<ol class="rank">{"".join(items)}</ol>'


def simple_list(items, empty="Nothing here yet."):
    """items: (title, subtitle, value)."""
    if not items:
        return f'<div class="empty">{e(empty)}</div>'
    lis = "".join(f'<li><span class="t"><b>{e(t)}</b><span>{e(s)}</span></span><span class="v">{e(v)}</span></li>'
                  for t, s, v in items)
    return f'<ol class="rank">{lis}</ol>'


def links(items, empty="None yet."):
    """items: (href, title, subtitle, value) - a list of report links."""
    if not items:
        return f'<div class="empty">{e(empty)}</div>'
    lis = "".join(f'<li><a href="{e(h)}"><span class="t"><b>{e(t)}</b><span>{e(s)}</span></span>'
                  f'<span class="v">{e(v)}</span></a></li>' for h, t, s, v in items)
    return f'<ol class="rank">{lis}</ol>'


def _ramp(v, vmax):
    if v <= 0 or vmax <= 0:
        return None
    return RAMP[min(len(RAMP) - 1, int((v / vmax) ** 0.7 * (len(RAMP) - 1) + 0.5))]


DAYS = ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"]


def heatmap(grid):
    vmax = max(max(r) for r in grid)
    if vmax <= 0:
        return '<div class="empty">No plays logged on this Mac in this period.</div>'
    cells = ['<span></span>'] + [f'<span class="hl">{h if h % 3 == 0 else ""}</span>' for h in range(24)]
    for d, row in enumerate(grid):
        cells.append(f'<span class="rl">{DAYS[d]}</span>')
        for h, v in enumerate(row):
            c = _ramp(v, vmax)
            style = f' style="background:{c}"' if c else ""
            cells.append(f'<span class="c" data-tip="{DAYS[d]} {h:02d}:00 · {round(v)} min"{style}></span>')
    legend = "".join(f'<i style="background:{c}"></i>' for c in RAMP)
    table = "".join(f"<tr><th>{DAYS[d]}</th>" + "".join(f"<td>{round(v)}</td>" for v in row) + "</tr>"
                    for d, row in enumerate(grid))
    hdr = "<tr><th></th>" + "".join(f"<th>{h}</th>" for h in range(24)) + "</tr>"
    return (f'<div class="chart heat">{"".join(cells)}</div>'
            f'<div class="legend">Less <i style="background:var(--cell)"></i>{legend} More (minutes)</div>'
            f'<details><summary>Show as table (minutes)</summary><div style="overflow-x:auto"><table>{hdr}{table}</table></div></details>')


def bars(series, unit="h"):
    """series: [(label, value, tooltip)] - one series, so no legend."""
    if not series or max(v for _, v, _ in series) <= 0:
        return '<div class="empty">No listening logged in this period.</div>'
    vmax = max(v for _, v, _ in series)
    bs = "".join(f'<div class="b" data-tip="{e(tip)}"><em>{v:.1f}</em><i style="height:{max(1, v / vmax * 100):.1f}%"></i></div>'
                 for _, v, tip in series)
    ls = "".join(f"<span>{e(lab)}</span>" for lab, _, _ in series)
    return f'<div class="chart bars">{bs}</div><div class="blabels">{ls}</div>'


def rank_grid(artists, weeks, data):
    """Rows = artists, columns = weeks; cell = rank that week, shaded by plays.

    data[artist][week_label] = (rank or None, plays)
    """
    if not artists:
        return '<div class="empty">No listening logged in this period.</div>'
    vmax = max((p for a in artists for _, p in data[a].values()), default=0)
    head = "<tr><th></th>" + "".join(f"<th>{e(w)}</th>" for w in weeks) + "</tr>"
    body = []
    for a in artists:
        tds = []
        for w in weeks:
            rank, plays = data[a][w]
            c = _ramp(plays, vmax)
            ink = "#08130c" if c in RAMP[3:] else "#f4f4f6"
            style = f' style="background:{c};color:{ink}"' if c else ""
            label = f"#{rank}" if rank else "–"
            tds.append(f'<td data-tip="{e(a)} · {w}: {fmt_plays(plays)}"{style}>{label}</td>')
        body.append(f'<tr><th class="a" title="{e(a)}">{e(a)}</th>{"".join(tds)}</tr>')
    return (f'<div style="overflow-x:auto"><table class="rg">{head}{"".join(body)}</table></div>'
            '<div class="legend">Cell = that week\'s artist rank; brighter = more plays.</div>')


def months(items):
    """items: (month name, song, artist, plays, pid) or (month name, None, None, 0, None)."""
    tiles = []
    for m, song, artist, n, pid in items:
        if song:
            tiles.append(f'<div class="month">{cover(pid, song)}<div><small>{e(m)}</small><b>{e(song)}</b>'
                         f'<span>{e(artist)} · {e(fmt_plays(n))}</span></div></div>')
        else:
            tiles.append(f'<div class="month"><div><small>{e(m)}</small><b>—</b><span>No plays logged</span></div></div>')
    return f'<div class="months">{"".join(tiles)}</div>'


def headline(big, sub="", pid=None, round_=False, art=False):
    text = f'<div class="big">{e(big)}</div>' + (f'<div class="sub">{e(sub)}</div>' if sub else "")
    if not art:
        return text
    return f'<div class="hl">{cover(pid, big, round_)}<div>{text}</div></div>'
