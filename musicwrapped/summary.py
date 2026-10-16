"""summary.json for the Übersicht widget. Same format the Swift logger writes after each play."""

import json
import os
from datetime import date, datetime

from . import paths, stats as S
from .reports import week_of


def build(con, today=None):
    today = today or date.today()
    start, end = week_of(today)
    plays = S.plays_between(con, start, end)
    artist = S.top_artists(plays, 1)
    song = S.top_songs(plays, 1)
    genre = S.top_genres(plays, 1)
    y, w, _ = start.isocalendar()
    return {
        "generated_at": datetime.now().astimezone().isoformat(timespec="seconds"),
        "week": f"{y}-W{w:02d}",
        "week_start": start.isoformat(),
        "hours": round(S.hours(plays), 1),
        "plays": len(plays),
        "top_artist": {"name": artist[0].name, "plays": artist[0].plays, "pid": artist[0].pid} if artist else None,
        "top_song": {"title": song[0].name, "artist": song[0].sub, "plays": song[0].plays, "pid": song[0].pid} if song else None,
        # Minutes per day, Monday first (7 values), for the widget's little chart.
        "daily_minutes": [round(sum(p.seconds for p in plays if p.dt.weekday() == i) / 60, 1) for i in range(7)],
        "top_genre": {"name": genre[0].name, "plays": genre[0].plays} if genre else None,
    }


def write(con):
    data = build(con)
    tmp = paths.SUMMARY.with_suffix(".json.tmp")
    tmp.write_text(json.dumps(data, indent=2, sort_keys=True, ensure_ascii=False))
    os.replace(tmp, paths.SUMMARY)
    return data
