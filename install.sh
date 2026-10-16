#!/bin/sh
# Installs music-wrapped for the current user. Safe to re-run (it updates everything).
set -eu

REPO="$(cd "$(dirname "$0")" && pwd)"
SUPPORT="$HOME/Library/Application Support/music-wrapped"
AGENTS="$HOME/Library/LaunchAgents"
LOGS="$SUPPORT/logs"
CLI="$REPO/bin/music-wrapped"
UID_="$(id -u)"

say() { printf '\033[1m==> %s\033[0m\n' "$*"; }

command -v swiftc >/dev/null || { echo "swiftc not found. Install the Command Line Tools: xcode-select --install"; exit 1; }
[ -x /usr/bin/python3 ] && /usr/bin/python3 -c 'import sys; sys.exit(sys.version_info < (3, 9))' \
  || { echo "Python 3.9+ not found. Install the Command Line Tools: xcode-select --install"; exit 1; }

mkdir -p "$SUPPORT/bin" "$LOGS" "$SUPPORT/reports" "$AGENTS"

say "Building the logger"
swiftc -O -o "$SUPPORT/bin/music-wrapped-logger" "$REPO/logger/main.swift"

if ! command -v terminal-notifier >/dev/null 2>&1 && [ ! -x /opt/homebrew/bin/terminal-notifier ]; then
  if command -v brew >/dev/null 2>&1; then
    say "Installing terminal-notifier (clickable notifications)"
    brew install terminal-notifier || echo "  (skipped; notifications will still show, just not clickable)"
  else
    echo "  Homebrew not found: notifications will show, but clicking them won't open the report."
  fi
fi

say "Linking the music-wrapped command into ~/.local/bin"
mkdir -p "$HOME/.local/bin"
ln -sf "$CLI" "$HOME/.local/bin/music-wrapped"

# plist <label> <run-at-load true|false> <calendar xml or ""> <args...>
plist() {
  label="$1"; atload="$2"; cal="$3"; shift 3
  args=""
  for a in "$@"; do args="$args<string>$a</string>"; done
  keepalive=""
  [ "$label" = "com.musicwrapped.logger" ] && keepalive="<key>KeepAlive</key><true/>"
  cat > "$AGENTS/$label.plist" <<PLIST
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0"><dict>
  <key>Label</key><string>$label</string>
  <key>ProgramArguments</key><array>$args</array>
  <key>RunAtLoad</key><$atload/>
  $keepalive
  $cal
  <key>Nice</key><integer>5</integer>
  <key>LowPriorityIO</key><true/>
  <key>EnvironmentVariables</key><dict>
    <key>PATH</key><string>/opt/homebrew/bin:/usr/local/bin:/usr/bin:/bin:/usr/sbin:/sbin</string>
  </dict>
  <key>StandardOutPath</key><string>$LOGS/${label#com.musicwrapped.}.log</string>
  <key>StandardErrorPath</key><string>$LOGS/${label#com.musicwrapped.}.log</string>
</dict></plist>
PLIST
  launchctl bootout "gui/$UID_/$label" 2>/dev/null || true
  launchctl bootstrap "gui/$UID_" "$AGENTS/$label.plist"
}

cal() { printf '<key>StartCalendarInterval</key><dict>%s</dict>' "$1"; }
k() { printf '<key>%s</key><integer>%s</integer>' "$1" "$2"; }

say "Installing launchd agents"
plist com.musicwrapped.logger   true  ""                                              "$SUPPORT/bin/music-wrapped-logger"
plist com.musicwrapped.snapshot false "$(cal "$(k Hour 12)$(k Minute 0)")"            "$CLI" snapshot --kind daily
plist com.musicwrapped.weekly   false "$(cal "$(k Weekday 0)$(k Hour 22)$(k Minute 0)")" "$CLI" report weekly --scheduled
plist com.musicwrapped.monthly  false "$(cal "$(k Day 1)$(k Hour 9)$(k Minute 0)")"    "$CLI" report monthly --scheduled
plist com.musicwrapped.yearly   false "$(cal "$(k Month 12)$(k Day 1)$(k Hour 9)$(k Minute 5)")" "$CLI" report yearly --scheduled

say "Backfilling your library (approve 'Terminal wants to control Music' if asked)"
"$CLI" backfill || echo "  Backfill failed; approve the Automation prompt, then run: music-wrapped backfill"

say "Running the daily snapshot job once (approve its 'control Music' prompt too, if one appears)"
launchctl kickstart "gui/$UID_/com.musicwrapped.snapshot" || true

echo
"$CLI" status
case ":$PATH:" in *":$HOME/.local/bin:"*) ;; *)
  echo
  echo "Add ~/.local/bin to your PATH to use the command anywhere:"
  echo "  echo 'export PATH=\"\$HOME/.local/bin:\$PATH\"' >> ~/.zshrc && source ~/.zshrc" ;;
esac
echo
echo "Done. Try: music-wrapped report weekly"
