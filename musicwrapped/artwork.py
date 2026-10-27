"""Album artwork for reports, exported from the Music library once per track and cached.

Reports mark cover slots with the CSS class `a-<PID>`; inject() looks up those tracks'
artwork and adds one CSS rule per image, so each image is embedded once per page.
"""

import base64
import re
import subprocess
import tempfile
import time
from pathlib import Path

from . import library, paths

ENABLED = True          # demo.py turns this off (its tracks aren't in your library)
ALLOW_LAUNCH = True     # live rebuilds never start Music; missing covers are fetched next time
SIZE = 160              # px, about 2x the largest cover shown
RETRY_DAYS = 7          # how long to remember "this track has no artwork"

SCRIPT = """
on run argv
    repeat with i from 1 to (count of argv) by 2
        set pid to item i of argv
        set outPath to item (i + 1) of argv
        set d to missing value
        tell application "Music"
            try
                set t to (first track of library playlist 1 whose persistent ID is pid)
                if (count of artworks of t) > 0 then set d to raw data of artwork 1 of t
            end try
        end tell
        if d is not missing value then
            set f to open for access (POSIX file outPath) with write permission
            set eof f to 0
            write d to f
            close access f
        end if
    end repeat
end run
"""

# Music's persistent IDs, or "YT…" ids for songs from other apps (YT Music). The logger saves those
# covers itself from Now Playing; Music can't export them.
PID_RE = re.compile(r"\ba-((?:YT[0-9A-F]{14})|[0-9A-F]{16})\b")
BIG_RE = re.compile(r"\bx-((?:YT[0-9A-F]{14})|[0-9A-F]{16})\b")
BIG = 640  # px, slides and story images


def _dir(size=SIZE):
    """artwork/ holds the report size; other sizes (stories) get their own subfolder."""
    d = paths.SUPPORT / "artwork"
    if size != SIZE:
        d = d / str(size)
    d.mkdir(parents=True, exist_ok=True)
    return d


def _missing(pids, size=SIZE):
    out = []
    for pid in pids:
        if pid.startswith("YT") or (_dir(size) / f"{pid}.jpg").exists():
            continue
        none = _dir(size) / f"{pid}.none"
        if none.exists() and time.time() - none.stat().st_mtime < RETRY_DAYS * 86400:
            continue
        out.append(pid)
    return out


def fetch(pids, size=SIZE):
    """Exports artwork for tracks not cached yet. Starts Music hidden if needed."""
    todo = _missing(sorted(set(pids)), size)
    if not todo or (not ALLOW_LAUNCH and not library.music_running()):
        return
    with tempfile.TemporaryDirectory() as tmp, library.music_session():
        raw = {pid: Path(tmp) / f"{pid}.raw" for pid in todo}
        args = [x for pid in todo for x in (pid, str(raw[pid]))]
        r = subprocess.run(["osascript", "-e", SCRIPT, *args], capture_output=True, text=True, timeout=600)
        if r.returncode != 0:
            print(f"artwork: {r.stderr.strip()}")
            return  # e.g. no permission: try again next time
        for pid in todo:
            out = _dir(size) / f"{pid}.jpg"
            ok = raw[pid].exists() and subprocess.run(
                ["sips", "-s", "format", "jpeg", "-s", "formatOptions", "85", "-Z", str(size), str(raw[pid]), "--out", str(out)],
                capture_output=True).returncode == 0
            if not ok:
                (_dir(size) / f"{pid}.none").touch()


def inject(html):
    """Adds cover images for every `a-<PID>` (160 px) and `x-<PID>` (640 px) slot in the page."""
    if not ENABLED:
        return html
    rules = []
    for prefix, regex, size in (("a", PID_RE, SIZE), ("x", BIG_RE, BIG)):
        pids = set(regex.findall(html))
        if not pids:
            continue
        try:
            fetch(pids, size)
        except (OSError, subprocess.SubprocessError, library.MusicError) as ex:
            print(f"artwork skipped: {ex}")
        for pid in sorted(pids):
            f = _dir(size) / f"{pid}.jpg"
            if f.exists():
                b64 = base64.b64encode(f.read_bytes()).decode()
                rules.append(f".art.{prefix}-{pid}{{background-image:url(data:image/jpeg;base64,{b64});color:transparent}}")
    if not rules:
        return html
    return html.replace("</style>", "\n" + "\n".join(rules) + "\n</style>", 1)
