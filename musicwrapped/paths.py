"""Where everything lives. Nothing personal is ever written inside the repo."""

import os
from pathlib import Path

SUPPORT = Path(os.environ.get("MUSIC_WRAPPED_HOME",
                              Path.home() / "Library/Application Support/music-wrapped"))
DB = SUPPORT / "plays.db"
REPORTS = SUPPORT / "reports"
SUMMARY = SUPPORT / "summary.json"
CONFIG = SUPPORT / "config.json"
LOGS = SUPPORT / "logs"
REPORT_KINDS = ("weekly", "monthly", "yearly", "alltime", "custom")
