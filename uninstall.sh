#!/bin/sh
# Removes the launchd agents and the command. Keeps your data unless you pass --purge.
set -u
UID_="$(id -u)"
SUPPORT="$HOME/Library/Application Support/music-wrapped"
for l in logger snapshot weekly monthly yearly; do
  launchctl bootout "gui/$UID_/com.musicwrapped.$l" 2>/dev/null
  rm -f "$HOME/Library/LaunchAgents/com.musicwrapped.$l.plist"
done
rm -f "$HOME/.local/bin/music-wrapped" "$SUPPORT/bin/music-wrapped-logger"
if [ "${1:-}" = "--purge" ]; then
  rm -rf "$SUPPORT"
  echo "Removed everything, including plays.db and reports."
else
  echo "Uninstalled. Your data is still in: $SUPPORT  (run with --purge to delete it)"
fi
