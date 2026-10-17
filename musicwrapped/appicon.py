"""The Music Wrapped.app icon: the cassette mascot on the report gradient, as a 1024x1024 page that
the story renderer turns into a PNG (tools/make-app.sh makes the .icns from it)."""

from . import render as R


def html():
    # macOS icon grid: an 824 px rounded square centred on a transparent 1024 px canvas.
    return f"""<!doctype html><html><head><meta charset="utf-8"><style>
html,body{{margin:0;width:1024px;height:1024px;background:transparent;overflow:hidden}}
.sq{{position:absolute;left:100px;top:100px;width:824px;height:824px;border-radius:185px;overflow:hidden;
  background:radial-gradient(120% 120% at 0% 0%,#ff4fa3 0%,transparent 55%),
    radial-gradient(120% 120% at 100% 100%,#1ed760 0%,transparent 50%),linear-gradient(135deg,#5b21d6,#2f6bff);
  box-shadow:0 10px 24px rgba(0,0,0,.28)}}
.m{{position:absolute;left:152px;top:250px;width:520px;height:325px}}
.m svg{{width:100%;height:100%;shape-rendering:crispEdges;filter:drop-shadow(0 18px 22px rgba(0,0,0,.35))}}
</style></head><body><div class="sq"><div class="m">{R.MASCOT}</div></div></body></html>"""
