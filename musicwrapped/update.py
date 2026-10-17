"""music-wrapped update: pull the latest code and rebuild only what changed.

Python changes need nothing (the command runs the repo's code directly). Swift parts are rebuilt when
their source changed: the logger (then signed and restarted), the story renderer, Music Wrapped.app.
If install.sh itself changed (e.g. new launchd jobs), it's re-run. Last, every launchd job is checked
and reloaded if it isn't running.
"""

import os
import subprocess
import tempfile
from pathlib import Path

from . import health, paths

REPO = Path(__file__).resolve().parent.parent
AGENTS_DIR = Path.home() / "Library/LaunchAgents"


def _git(*args, check=True):
    return subprocess.run(["git", "-C", str(REPO), *args], capture_output=True, text=True, check=check).stdout.rstrip()


def _run(cmd, **kw):
    print("  $ " + " ".join(str(c) for c in cmd))
    return subprocess.run([str(c) for c in cmd], check=True, **kw)


def rebuild_logger():
    """Build next to the running binary, sign it with the local certificate, swap it in, restart."""
    dest = paths.SUPPORT / "bin/music-wrapped-logger"
    dest.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(dir=dest.parent) as tmp:
        new = Path(tmp) / "music-wrapped-logger"
        _run(["swiftc", "-O", "-o", new, REPO / "logger/main.swift"])
        try:
            _run([REPO / "tools/sign-logger.sh", new])
        except subprocess.CalledProcessError:
            print("  Signing failed; macOS may ask again whether the logger may control Music.")
        os.replace(new, dest)   # the logger always runs from dest, so this is the switch-over
    subprocess.run(["launchctl", "kickstart", "-k", f"gui/{os.getuid()}/com.musicwrapped.logger"], check=False)


def rebuild_renderer():
    _run(["swiftc", "-O", "-o", paths.SUPPORT / "bin/music-wrapped-render", REPO / "renderer/main.swift"])


def rebuild_app():
    _run([REPO / "tools/make-app.sh", paths.SUPPORT / "bin/music-wrapped-render", Path.home() / "Applications"],
         stdout=subprocess.DEVNULL)


def check_agents():
    """Reload any launchd job that isn't loaded. Returns the ones still missing."""
    listed = subprocess.run(["launchctl", "list"], capture_output=True, text=True).stdout
    missing = []
    for a in health.AGENTS:
        label = f"com.musicwrapped.{a}"
        if label in listed:
            continue
        plist = AGENTS_DIR / f"{label}.plist"
        ok = plist.exists() and subprocess.run(["launchctl", "bootstrap", f"gui/{os.getuid()}", str(plist)],
                                               capture_output=True).returncode == 0
        print(f"  {'reloaded' if ok else 'NOT loaded'}: {label}")
        if not ok:
            missing.append(label)
    return missing


def run(rebuild=False, pull=True):
    if not (REPO / ".git").exists():
        print(f"{REPO} isn't a git checkout, so there's nothing to pull. Download the latest version, then run ./install.sh.")
        return 1
    if _git("status", "--porcelain", "--untracked-files=no"):
        print("You have local changes to music-wrapped's files. Commit or stash them first:")
        print(_git("status", "--short", "--untracked-files=no"))
        return 1
    old = _git("rev-parse", "HEAD")
    if pull:
        print("Getting the latest version…")
        r = subprocess.run(["git", "-C", str(REPO), "pull", "--ff-only", "--quiet"], capture_output=True, text=True)
        if r.returncode:
            print("  Couldn't pull: " + (r.stderr.strip().splitlines() or ["unknown error"])[-1])
            return 1
    new = _git("rev-parse", "HEAD")
    changed = set(_git("diff", "--name-only", old, new).splitlines()) if old != new else set()
    if old == new:
        print("Already up to date." + (" Rebuilding everything anyway." if rebuild else ""))
    else:
        print(f"Updated {old[:7]} → {new[:7]}:")
        print("\n".join("  " + line for line in _git("log", "--oneline", f"{old}..{new}").splitlines()))

    if "install.sh" in changed:
        # New or changed launchd jobs: the installer is safe to re-run and rebuilds everything.
        print("\nThe installer changed, so running it again…")
        _run([REPO / "install.sh"])
        return 1 if check_agents() else 0

    steps = []
    if rebuild or "logger/main.swift" in changed or "tools/sign-logger.sh" in changed:
        steps.append(("Rebuilding the logger", rebuild_logger))
    if rebuild or "renderer/main.swift" in changed:
        steps.append(("Rebuilding the story renderer", rebuild_renderer))
    app_files = {"app/main.swift", "tools/make-app.sh", "musicwrapped/appicon.py", "renderer/main.swift"}
    if rebuild or changed & app_files or not (Path.home() / "Applications/Music Wrapped.app").exists():
        steps.append(("Rebuilding Music Wrapped.app", rebuild_app))
    for title, fn in steps:
        print(f"\n{title}…")
        try:
            fn()
        except (OSError, subprocess.CalledProcessError) as ex:
            print(f"  Failed ({ex}). Run ./install.sh to rebuild everything.")
            return 1
    if not steps:
        print("\nNothing to rebuild: Python changes take effect right away.")

    print("\nChecking the background jobs…")
    missing = check_agents()
    if missing:
        print("Some jobs couldn't be loaded. Run ./install.sh to set them up again.")
        return 1
    print(f"All {len(health.AGENTS)} background jobs are running. Done.")
    return 0
