# music-wrapped

A personal, Spotify-Wrapped-style recap of your **Apple Music** listening, for Apple Silicon Macs.
Everything is free and local: no paid APIs, no Apple developer account, no data leaves your Mac.

- **Logs every play on your Mac** with a tiny background helper that sleeps until the Music app
  announces a track change (`com.apple.Music.playerInfo`). No polling, nothing runs when Music is closed.
- **Imports your whole library** (play counts, last played, durations) for all-time stats.
- **Picks up iPhone (and other device) plays** from synced play counts, once a day and before every report.
- **Generates Wrapped pages** (weekly, monthly, yearly, all-time and custom ranges) as single self-contained
  HTML files, with a clickable macOS notification when a scheduled one is ready.
- **Writes `summary.json`** (this week's hours, top artist, top song) for desktop widgets.

## Requirements

- macOS on Apple Silicon (tested on macOS 27), with the Music app
- Command Line Tools (`xcode-select --install`), which provide `swiftc` and `python3` (3.9+)
- Optional: [Homebrew](https://brew.sh). The installer uses it to add `terminal-notifier` so notifications are clickable
- For iPhone plays: **Sync Library** turned on (Music → Settings → General on the Mac, Settings → Apps → Music on the iPhone)

## Install

```sh
git clone https://github.com/<you>/music-wrapped.git
cd music-wrapped
./install.sh
```

The installer:

1. Builds the logger (`logger/main.swift`) into `$HOME/Library/Application Support/music-wrapped/bin/`.
2. Installs `terminal-notifier` with Homebrew, if it's missing.
3. Links the `music-wrapped` command into `$HOME/.local/bin`.
4. Installs five launchd agents in `$HOME/Library/LaunchAgents`:

   | Agent | When | What |
   |---|---|---|
   | `com.musicwrapped.logger` | at login, kept alive | logs Mac plays |
   | `com.musicwrapped.snapshot` | daily 12:00 | play-count snapshot (other-device plays) |
   | `com.musicwrapped.weekly` | Sunday 22:00 | weekly report + all-time refresh |
   | `com.musicwrapped.monthly` | 1st of the month, 09:00 | last month's report |
   | `com.musicwrapped.yearly` | 1 December, 09:05 | Jan–Nov Wrapped |

   If the Mac is asleep at a scheduled time, launchd runs the job when it wakes up.
5. Runs the **backfill** (first library snapshot).

To uninstall: `./uninstall.sh` (keeps your data) or `./uninstall.sh --purge`.

## Permission prompts to expect

| Prompt | Why | Approve? |
|---|---|---|
| **"Terminal" wants access to control "Music"** | the backfill and manual reports read your library with AppleScript | Yes |
| **"sh" / "python3" / "osascript" wants access to control "Music"** (wording varies) | the same library read, when launchd runs the daily snapshot. The installer runs that job once so this prompt shows up during install | Yes |
| **"Background Items Added"** notification (one per agent, shown as "sh" or "music-wrapped-logger") | macOS tells you about new login/background items | Leave them enabled in System Settings → General → Login Items & Extensions |
| **"terminal-notifier" would like to send notifications** | shows up with the first report notification | Allow |
| Poll mode only: **"music-wrapped-logger" wants access to control "Music"** | only if you switch to polling (see below) | Yes |

The default event-driven logger needs **no** permissions: it only listens to notifications that Music broadcasts.
Manage these later in System Settings → Privacy & Security → Automation.

## Usage

```sh
music-wrapped report weekly                # this week so far (ISO week, Mon–Sun)
music-wrapped report weekly --week 2026-W40
music-wrapped report monthly               # last month
music-wrapped report monthly --current     # this month so far
music-wrapped report monthly --month 2026-09
music-wrapped report yearly                # this year, Jan–Nov (so far, before December)
music-wrapped report alltime
music-wrapped custom 2026-09-01 2026-12-31 --name "Semester 1"

music-wrapped open                         # newest report of any kind
music-wrapped open weekly                  # reports/weekly/latest.html

music-wrapped status                       # what's logged, agents loaded, latest reports
music-wrapped snapshot                     # pick up iPhone plays now
music-wrapped summary                      # rewrite + print summary.json
music-wrapped doctor                       # check that Music's notifications arrive
music-wrapped demo                         # preview every report with fake data
```

Every report command takes a library snapshot first (skip it with `--no-snapshot`) and opens the result
in your browser (skip with `--no-open`). Scheduled runs only send a notification; clicking it opens the report.

## Try it right away

You don't have to wait a week:

```sh
music-wrapped demo                     # 1. see what every report looks like (fake data, separate folder)
music-wrapped doctor                   # 2. play/pause/skip in Music during the 45 s test
# 3. listen to a few songs for 30+ s each, then:
music-wrapped status                   #    plays logged today
music-wrapped report weekly            # 4. real reports: today's plays...
music-wrapped report monthly --current
music-wrapped report yearly
music-wrapped report alltime           #    ...and your whole library from the backfill
music-wrapped custom 2026-10-01 2026-10-31 --name "Test"
```

iPhone plays show up after the **second** snapshot (the first one is only a baseline): play something on
your iPhone, wait a few minutes for iCloud to sync, then run `music-wrapped snapshot`.

## How counting works

- **Mac plays**: a play counts after **30 s** of actual listening (pauses and sleep don't count). It's
  marked **skipped** if it stopped before 50% of the track. Each play is one row: timestamp, title, artist,
  album, duration, seconds listened, skipped and `source = 'mac'`.
- **Other devices**: each snapshot compares every track's library play count with the previous snapshot.
  A track seen for the first time (in the backfill or any later snapshot, e.g. a song you just added on your
  iPhone) only gets a **baseline**: its existing play count is never counted as plays; only increases after
  that are. Music only increments a play count when a song plays to (about) the end, so Mac plays that reached ≥ 90% of
  the track are subtracted, and the rest of the increase becomes `source = 'other'` rows. Their time is the
  track's "last played" date (the exact times of several plays aren't known), and listening time is
  estimated as the track length. Skips can't be known for them.
- **All-time** reports use the library play counts directly, the true total across all devices.
- **Date-range** reports (weekly, monthly, yearly, custom) add up the logged rows in that range,
  so 3 plays one week + 5 the next = 8 in that month. Nothing is counted twice.
- **Heatmap and skips are Mac only**; top lists, on-repeat, new artists and hours include all devices.
- **New artists** = no logged plays before the period, no library track by that artist added or played
  before it, and no baseline plays from before the period (plays already in the library at backfill time can't be
  dated, so they always count as "before"). So in your
  first year, the "biggest new discovery" only considers artists you start listening to after installing.

## Files

Everything personal lives outside the repo, in `$HOME/Library/Application Support/music-wrapped/`:

```
plays.db              SQLite: plays (every play, kept forever), library (all-time stats), snapshots (log)
summary.json          widget summary, rewritten after every play and report
config.json           {"mode": "notifications" | "poll"}
reports/weekly/       2026-W42.html … latest.html
reports/monthly/      2026-10.html … latest.html
reports/yearly/       2026.html … latest.html
reports/alltime/      2026-10-17.html … latest.html
reports/custom/       2026-09-01_to_2026-12-31_semester-1.html … latest.html
logs/                 launchd job output
bin/                  the compiled logger
demo/                 output of `music-wrapped demo`
```

`summary.json`:

```json
{
  "generated_at": "2026-10-17T21:04:11+08:00",
  "week": "2026-W42",
  "week_start": "2026-10-12",
  "hours": 3.6,
  "plays": 61,
  "top_artist": {"name": "…", "plays": 15},
  "top_song": {"title": "…", "artist": "…", "plays": 6}
}
```

`top_artist` / `top_song` are `null` when nothing has been played this week.

## Fallback: polling

If `music-wrapped doctor` receives no notifications, run `music-wrapped mode poll`. The logger then asks Music
for its state every 30 s via AppleScript, only while Music is running. Switch back with
`music-wrapped mode notifications`.

## Limitations

- If the logger starts while a song is already playing, that song is picked up at the next play/pause/track change.
- Plays on other devices only reach the Mac when iCloud syncs play counts, and their exact times are approximate.
- The Sunday 22:00 weekly report doesn't include the last two hours of Sunday. Re-run
  `music-wrapped report weekly --week <week>` to regenerate it.

## Development

```sh
python3 -m unittest discover tests     # counting rules
swiftc -O -o build/music-wrapped-logger logger/main.swift
build/music-wrapped-logger --probe 30  # print raw Music notifications
MUSIC_WRAPPED_HOME=/tmp/mw music-wrapped demo   # use a different data folder
```

## License

MIT. Not affiliated with Apple or Spotify.
