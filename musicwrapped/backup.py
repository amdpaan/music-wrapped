"""Backups of plays.db: dated copies on this Mac, plus an optional private GitHub repo.

The GitHub copy is a plain-text SQL dump (plays.sql), so each weekly commit only stores
the rows that changed and the repo stays small. Restore with:
    sqlite3 plays.db < plays.sql
"""

import json
import os
import shutil
import sqlite3
import subprocess
from datetime import date

from . import paths

KEEP = 8
EXTRA_PATH = "/opt/homebrew/bin:/usr/local/bin:/usr/bin:/bin"


def _dir():
    return paths.SUPPORT / "backups"


def _repo_dir():
    return paths.SUPPORT / "backup-repo"


def _config():
    try:
        return json.loads(paths.CONFIG.read_text())
    except (OSError, ValueError):
        return {}


def _save_config(cfg):
    paths.CONFIG.write_text(json.dumps(cfg, indent=2))


def local():
    """Copies plays.db to backups/plays-YYYY-MM-DD.db (safe while the logger writes) and keeps the newest 8."""
    folder = _dir()
    folder.mkdir(parents=True, exist_ok=True)
    out = folder / f"plays-{date.today()}.db"
    src = sqlite3.connect(str(paths.DB))
    dst = sqlite3.connect(str(out))
    with dst:
        src.backup(dst)
    src.close()
    dst.close()
    for old in sorted(folder.glob("plays-*.db"))[:-KEEP]:
        old.unlink()
    return out


def _env():
    return {**os.environ, "PATH": f"{EXTRA_PATH}:{os.environ.get('PATH', '')}"}


def _run(args, cwd=None):
    r = subprocess.run(args, cwd=cwd, capture_output=True, text=True, env=_env())
    if r.returncode != 0:
        raise RuntimeError(f"{' '.join(args[:3])}: {(r.stderr or r.stdout).strip()}")
    return r.stdout.strip()


def _gh():
    gh = shutil.which("gh", path=EXTRA_PATH)
    if not gh:
        raise RuntimeError("GitHub CLI (gh) not found. Install it with: brew install gh && gh auth login")
    return gh


def setup_github(name=None):
    """Creates (or reuses) a private repo, clones it and remembers it in config.json."""
    gh = _gh()
    user = json.loads(_run([gh, "api", "user"]))
    name = name or f"{user['login']}/music-wrapped-data"
    if "/" not in name:
        name = f"{user['login']}/{name}"
    exists = subprocess.run([gh, "repo", "view", name], capture_output=True, env=_env()).returncode == 0
    if exists:
        if _run([gh, "repo", "view", name, "--json", "visibility", "-q", ".visibility"]) != "PRIVATE":
            raise RuntimeError(f"{name} exists and is not private. Use another name with --repo.")
    else:
        _run([gh, "repo", "create", name, "--private",
              "--description", "Private backup of my music-wrapped listening history"])
    repo = _repo_dir()
    if repo.exists():
        shutil.rmtree(repo)
    _run([gh, "repo", "clone", name, str(repo)])
    # Commit as the GitHub noreply address, never a personal email.
    _run(["git", "config", "user.name", user.get("name") or user["login"]], cwd=repo)
    _run(["git", "config", "user.email", f"{user['id']}+{user['login']}@users.noreply.github.com"], cwd=repo)
    cfg = _config()
    cfg["backup_repo"] = name
    _save_config(cfg)
    return name


def github():
    """Commits a fresh SQL dump and pushes it. Returns a short status, or None if not set up."""
    name = _config().get("backup_repo")
    if not name:
        return None
    repo = _repo_dir()
    if not (repo / ".git").exists():
        setup_github(name)
    try:
        _run(["git", "pull", "--quiet", "--rebase"], cwd=repo)
    except RuntimeError:
        pass  # empty repo (no commits yet)
    con = sqlite3.connect(str(paths.DB))
    with open(repo / "plays.sql", "w", encoding="utf-8") as f:
        for line in con.iterdump():
            f.write(line + "\n")
    con.close()
    readme = repo / "README.md"
    if not readme.exists():
        readme.write_text("# music-wrapped data\n\nPrivate backup of `plays.db`. Restore with:\n\n"
                          "```sh\nsqlite3 plays.db < plays.sql\n```\n")
    _run(["git", "add", "-A"], cwd=repo)
    if not _run(["git", "status", "--porcelain"], cwd=repo):
        return f"{name}: no changes"
    _run(["git", "commit", "--quiet", "-m", f"Backup {date.today()}"], cwd=repo)
    _run(["git", "push", "--quiet", "-u", "origin", "HEAD"], cwd=repo)
    return f"{name}: pushed"


def run():
    """Local copy always; GitHub if configured. Returns lines to log."""
    out = [f"local backup: {local()}"]
    try:
        r = github()
        out.append(f"github backup: {r}" if r else "github backup: not set up (music-wrapped backup --setup-github)")
    except (RuntimeError, OSError) as ex:
        out.append(f"github backup failed: {ex}")
    return out
