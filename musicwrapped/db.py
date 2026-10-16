"""SQLite schema and connection. The Swift logger creates the same `plays` table."""

import sqlite3

from . import paths

SCHEMA = """
PRAGMA journal_mode=WAL;

-- One row per play. source = 'mac' (logged live) or 'other' (inferred from synced play counts).
CREATE TABLE IF NOT EXISTS plays (
    id INTEGER PRIMARY KEY,
    ts INTEGER NOT NULL,              -- start, unix seconds
    played_at TEXT NOT NULL,          -- start, local ISO 8601
    title TEXT NOT NULL,
    artist TEXT,
    album TEXT,
    duration REAL,                    -- track length, seconds
    seconds_listened REAL NOT NULL,   -- 'other' plays: estimated as the track duration
    skipped INTEGER,                  -- 1/0 for mac, NULL for other (unknown)
    source TEXT NOT NULL,
    persistent_id TEXT,
    ended_ts INTEGER NOT NULL         -- when the play was recorded
);
CREATE INDEX IF NOT EXISTS plays_ts ON plays(ts);
CREATE INDEX IF NOT EXISTS plays_pid ON plays(persistent_id, ended_ts);

-- Latest known state of every library track (the all-time stats).
CREATE TABLE IF NOT EXISTS library (
    persistent_id TEXT PRIMARY KEY,
    title TEXT, artist TEXT, album TEXT,
    duration REAL,
    play_count INTEGER NOT NULL DEFAULT 0,
    played_ts INTEGER,                -- last played date
    added_ts INTEGER,                 -- date added
    baseline_play_count INTEGER,      -- play count when first seen (backfill)
    first_seen_ts INTEGER NOT NULL,
    updated_ts INTEGER NOT NULL,
    in_library INTEGER NOT NULL DEFAULT 1
);
CREATE INDEX IF NOT EXISTS library_artist ON library(artist);

-- Log of every snapshot (the first one is the backfill).
CREATE TABLE IF NOT EXISTS snapshots (
    id INTEGER PRIMARY KEY,
    ts INTEGER NOT NULL,
    kind TEXT NOT NULL,               -- backfill | daily | report | manual
    tracks INTEGER NOT NULL,
    total_play_count INTEGER NOT NULL,
    other_plays_added INTEGER NOT NULL
);
"""


def connect():
    paths.SUPPORT.mkdir(parents=True, exist_ok=True)
    con = sqlite3.connect(str(paths.DB), timeout=10)
    con.row_factory = sqlite3.Row
    con.executescript(SCHEMA)
    return con
