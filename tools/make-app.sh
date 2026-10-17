#!/bin/sh
# Builds "Music Wrapped.app" (opens the reports home page) into the given folder, with the mascot icon.
# Usage: tools/make-app.sh <music-wrapped-render> <destination folder, e.g. ~/Applications>
set -eu
REPO="$(cd "$(dirname "$0")/.." && pwd)"
RENDER="$1"
DEST="$2"
TMP="$(mktemp -d)"
trap 'rm -rf "$TMP"' EXIT
APP="$TMP/Music Wrapped.app"
mkdir -p "$APP/Contents/MacOS" "$APP/Contents/Resources"

# An explicit deployment target: swiftc's default can be newer than the running macOS, and then
# Finder/Dock refuse to launch the app (error -10825) even though the binary runs fine.
swiftc -O -target "$(uname -m)-apple-macos12.0" -o "$APP/Contents/MacOS/Music Wrapped" "$REPO/app/main.swift"

cat > "$APP/Contents/Info.plist" <<PLIST
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0"><dict>
  <key>CFBundleIdentifier</key><string>com.musicwrapped.app</string>
  <key>CFBundleName</key><string>Music Wrapped</string>
  <key>CFBundleDisplayName</key><string>Music Wrapped</string>
  <key>CFBundleExecutable</key><string>Music Wrapped</string>
  <key>CFBundleIconFile</key><string>AppIcon</string>
  <key>CFBundlePackageType</key><string>APPL</string>
  <key>CFBundleShortVersionString</key><string>1.0</string>
  <key>CFBundleVersion</key><string>1</string>
  <key>LSApplicationCategoryType</key><string>public.app-category.music</string>
  <key>LSMinimumSystemVersion</key><string>12.0</string>
  <key>NSHighResolutionCapable</key><true/>
</dict></plist>
PLIST

# Icon: render the mascot page to a 1024 px PNG, then every size an .icns needs.
/usr/bin/python3 -c "import sys; sys.path.insert(0, sys.argv[1]); from musicwrapped import appicon; print(appicon.html())" \
  "$REPO" > "$TMP/icon.html"
"$RENDER" 1024 1024 "$TMP/icon.html" "$TMP/icon.png"
SET="$TMP/AppIcon.iconset"
mkdir "$SET"
for s in 16 32 128 256 512; do
  sips -z $s $s "$TMP/icon.png" --out "$SET/icon_${s}x${s}.png" >/dev/null
  d=$((s * 2))
  sips -z $d $d "$TMP/icon.png" --out "$SET/icon_${s}x${s}@2x.png" >/dev/null
done
iconutil -c icns "$SET" -o "$APP/Contents/Resources/AppIcon.icns"

codesign --force --sign - "$APP" >/dev/null 2>&1 || true

mkdir -p "$DEST"
rm -rf "$DEST/Music Wrapped.app"
cp -R "$APP" "$DEST/"
# Tell Finder/Launchpad/Spotlight about it (and refresh the icon on updates).
/System/Library/Frameworks/CoreServices.framework/Frameworks/LaunchServices.framework/Support/lsregister -f "$DEST/Music Wrapped.app" 2>/dev/null || true
touch "$DEST/Music Wrapped.app"
echo "$DEST/Music Wrapped.app"
