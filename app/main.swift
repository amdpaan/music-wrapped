// Music Wrapped.app: opens the reports home page in your browser, then quits.
// Built and installed into ~/Applications by install.sh (tools/make-app.sh).

import AppKit

let reports = FileManager.default.homeDirectoryForCurrentUser
    .appendingPathComponent("Library/Application Support/music-wrapped/reports")
let pages = ["index.html", "weekly/latest.html"].map { reports.appendingPathComponent($0) }

if let page = pages.first(where: { FileManager.default.fileExists(atPath: $0.path) }) {
    NSWorkspace.shared.open(page)
} else {
    NSApplication.shared.setActivationPolicy(.regular)
    NSApplication.shared.activate(ignoringOtherApps: true)
    let alert = NSAlert()
    alert.messageText = "No reports yet"
    alert.informativeText = "Play some music, or run “music-wrapped report weekly” in Terminal, then open Music Wrapped again."
    alert.runModal()
}
