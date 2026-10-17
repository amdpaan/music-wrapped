"""Shareable story images: the report's slides rendered as 1080x1920 PNGs (Instagram / WhatsApp
story size). Same design as the slides at the top of each report, with animations off.

Pages are rendered by renderer/main.swift with the system WebKit.
"""

import argparse
import shutil
import subprocess
import tempfile
from datetime import date, timedelta
from html import escape
from pathlib import Path

from . import artwork, paths, reports, render as R, slides as SL

W, H = 1080, 1920
REPO = Path(__file__).resolve().parent.parent

BASE_CSS = """
*{box-sizing:border-box;margin:0;padding:0}
html,body{width:1080px;height:1920px;overflow:hidden}
body{background:#09090d;color:#f4f4f6;font-family:-apple-system,BlinkMacSystemFont,"SF Pro Display","Helvetica Neue",Arial,sans-serif;
  -webkit-font-smoothing:antialiased}
#bg{position:fixed;inset:0;width:100%;height:100%;z-index:0}
.slide{padding:72px 56px 120px !important}
.brand{position:fixed;left:0;right:0;bottom:44px;z-index:2;display:flex;justify-content:center;align-items:center;gap:16px;
  font-size:26px;font-weight:800;letter-spacing:.12em;text-transform:uppercase;color:rgba(255,255,255,.6)}
a.more{display:none}
.brand .m{width:56px;height:35px}.brand .m svg{width:100%;height:100%;shape-rendering:crispEdges}
"""


def page(slide_html):
    return f"""<!doctype html><html class="static"><head><meta charset="utf-8">
<meta name="viewport" content="width={W}"><style>{BASE_CSS}{SL.CSS}</style></head>
<body><canvas id="bg"></canvas>{slide_html}
<div class="brand"><span class="m">{R.MASCOT}</span>Music Wrapped</div>{R.BG_JS}</body></html>"""


def slides_for(con, kind, a, today=None):
    """(period name, [(slide name, html)]) for a story."""
    today = today or date.today()
    if kind == "weekly":
        day = reports.parse_week(a.week) if a.week else today
        _, name, sl = reports.weekly(con, day, slides_only=True)
    elif kind == "monthly":
        if a.month:
            y, m = map(int, a.month.split("-"))
        elif a.current:
            y, m = today.year, today.month
        else:
            last = today.replace(day=1) - timedelta(days=1)
            y, m = last.year, last.month
        _, name, sl = reports.monthly(con, y, m, so_far=(y, m) == (today.year, today.month), slides_only=True)
    elif kind == "yearly":
        _, name, sl = reports.yearly(con, a.year or today.year, slides_only=True)
    else:
        _, name, sl = reports.alltime(con, slides_only=True)
    return name, sl


TITLES = {"weekly": "Your week", "monthly": "Your month", "yearly": "Your year", "alltime": "All time"}


def gallery(kind, name, files):
    """index.html next to the PNGs: every image, big, with how to save it (long-press on an iPhone)."""
    imgs = "".join(f'<a href="{escape(f)}"><img src="{escape(f)}" alt="Story image {i}" loading="lazy"></a>'
                   for i, f in enumerate(files, 1))
    return f"""<!doctype html><html lang="en"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1"><meta name="color-scheme" content="dark">
<title>{escape(TITLES.get(kind, "Your"))} in stories</title><style>
*{{box-sizing:border-box}}body{{margin:0;background:#09090d;color:#f4f4f6;padding:24px 16px 48px;
  font-family:-apple-system,BlinkMacSystemFont,"Helvetica Neue",Arial,sans-serif;-webkit-font-smoothing:antialiased}}
main{{max-width:1180px;margin:0 auto}}h1{{font-size:clamp(30px,7vw,56px);letter-spacing:-.03em;margin:8px 0 6px}}
p{{color:#a8a8b3;font-weight:600;margin:0 0 20px;line-height:1.45}}a.back{{color:#1ed760;font-weight:800;text-decoration:none}}
.g{{display:grid;grid-template-columns:repeat(auto-fill,minmax(min(100%,260px),1fr));gap:14px}}
.g img{{width:100%;aspect-ratio:9/16;display:block;border-radius:18px;background:#14141b}}
</style></head><body><main>
<a class="back" href="../../../reports/{escape(kind)}/{escape(name)}.html">← Back to the report</a>
<h1>{escape(TITLES.get(kind, "Your"))} in stories</h1>
<p>{len(files)} images, 1080×1920. On an iPhone: touch and hold an image, then <b>Save to Photos</b>.
On a Mac: drag them out, or right-click → Save Image As.</p>
<div class="g">{imgs}</div></main></body></html>"""


def args_for(kind, name):
    """The story command's arguments for a saved report (weekly 2026-W42, monthly 2026-10, yearly 2026)."""
    a = argparse.Namespace(week=None, month=None, current=False, year=None)
    if kind == "weekly":
        a.week = name
    elif kind == "monthly":
        a.month = name
    elif kind == "yearly":
        a.year = int(name)
    return a


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
    """Renders the story PNGs. Returns the output folder, or None if there's nothing to show."""
    name, sl = slides_for(con, kind, a)
    if not sl:
        return None
    out = paths.SUPPORT / "stories" / kind / name
    if out.exists():
        shutil.rmtree(out)
    out.mkdir(parents=True)
    with tempfile.TemporaryDirectory() as tmp:
        jobs = []
        for i, (slide_name, html) in enumerate(sl, 1):
            f = Path(tmp) / f"{i:02d}-{slide_name}.html"
            f.write_text(artwork.inject(page(html)), encoding="utf-8")
            jobs += [str(f), str(out / f"{i:02d}-{slide_name}.png")]
        subprocess.run([str(renderer()), str(W), str(H), *jobs], check=True, timeout=300)
    files = sorted(p.name for p in out.glob("*.png"))
    (out / "index.html").write_text(gallery(kind, name, files), encoding="utf-8")
    return out
