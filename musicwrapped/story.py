"""Shareable story images: the report's slides rendered as 1080x1920 PNGs (Instagram / WhatsApp
story size). Same design as the slides at the top of each report, with animations off.

Pages are rendered by renderer/main.swift with the system WebKit.
"""

import shutil
import subprocess
import tempfile
from datetime import date, timedelta
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
    return out
