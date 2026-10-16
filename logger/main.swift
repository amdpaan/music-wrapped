// music-wrapped-logger: records Apple Music plays on this Mac into SQLite.
//
// Default mode is event-driven: it sleeps in a run loop and only wakes when the
// Music app posts com.apple.Music.playerInfo (play / pause / stop / track change).
// It needs no AppleScript and no Automation permission in this mode.
//
// Fallback "poll" mode (config.json {"mode": "poll"}) asks Music for its state every
// 30 s via AppleScript, and only while Music is running.
//
// Usage:
//   music-wrapped-logger              run (launchd starts it at login)
//   music-wrapped-logger --probe 60   print playerInfo notifications for 60 s, then exit
//   music-wrapped-logger --refresh-cmd <path to music-wrapped>
//                                     also rebuild the weekly report after every logged play
//
// When launchd stops the logger, the song in progress is saved to pending.json rather than
// logged. On start, the logger asks Music once (AppleScript) what's playing: if it's the same
// song, it carries on with it, so a restart never logs one listen twice. Otherwise the saved
// song is logged and the current one is tracked from now on.

import AppKit
import Foundation
import SQLite3

let env = ProcessInfo.processInfo.environment
// Test settings (tests/test_logger.py): a private notification name so tests never reach the real
// logger, a shorter minimum, and a fake answer to "what is Music playing?".
let notificationName = Notification.Name(env["MUSIC_WRAPPED_NOTIFICATION"] ?? "com.apple.Music.playerInfo")
let minSeconds = Double(env["MUSIC_WRAPPED_MIN_SECONDS"] ?? "") ?? 30.0   // a play counts after 30 s of listening
let skipFraction = 0.5         // skipped = stopped before 50 %
let pollInterval = 30.0
let musicBundleID = "com.apple.Music"

let supportDir = ProcessInfo.processInfo.environment["MUSIC_WRAPPED_HOME"].map { URL(fileURLWithPath: $0) }
    ?? FileManager.default.homeDirectoryForCurrentUser.appendingPathComponent("Library/Application Support/music-wrapped")
let dbPath = supportDir.appendingPathComponent("plays.db").path
let summaryPath = supportDir.appendingPathComponent("summary.json")
let configPath = supportDir.appendingPathComponent("config.json")
let pendingPath = supportDir.appendingPathComponent("pending.json")
let heartbeatPath = supportDir.appendingPathComponent("heartbeat.json")   // read by `music-wrapped health`
let resumeWindow = 600.0       // resume a saved song only if we were stopped for under 10 min

func log(_ s: String) {
    let ts = ISO8601DateFormatter().string(from: Date())
    FileHandle.standardError.write("\(ts) \(s)\n".data(using: .utf8)!)
}

// MARK: - Date helpers

let isoLocal: DateFormatter = {
    let f = DateFormatter()
    f.locale = Locale(identifier: "en_US_POSIX")
    f.dateFormat = "yyyy-MM-dd'T'HH:mm:ssXXXXX"
    return f
}()

var isoCalendar: Calendar = {
    var c = Calendar(identifier: .iso8601)
    c.timeZone = .current
    return c
}()

// MARK: - SQLite

let SQLITE_TRANSIENT = unsafeBitCast(-1, to: sqlite3_destructor_type.self)

final class DB {
    var handle: OpaquePointer?

    init() {
        try? FileManager.default.createDirectory(at: supportDir, withIntermediateDirectories: true)
        guard sqlite3_open(dbPath, &handle) == SQLITE_OK else {
            log("cannot open \(dbPath)")
            exit(1)
        }
        sqlite3_busy_timeout(handle, 5000)
        // Keep in sync with musicwrapped/db.py (the Python side owns the full schema).
        exec("""
            PRAGMA journal_mode=WAL;
            CREATE TABLE IF NOT EXISTS plays (
                id INTEGER PRIMARY KEY,
                ts INTEGER NOT NULL,
                played_at TEXT NOT NULL,
                title TEXT NOT NULL,
                artist TEXT,
                album TEXT,
                duration REAL,
                seconds_listened REAL NOT NULL,
                skipped INTEGER,
                source TEXT NOT NULL,
                persistent_id TEXT,
                ended_ts INTEGER NOT NULL,
                genre TEXT
            );
            CREATE INDEX IF NOT EXISTS plays_ts ON plays(ts);
            CREATE INDEX IF NOT EXISTS plays_pid ON plays(persistent_id, ended_ts);
            """)
        // Databases from before genres were tracked (musicwrapped/db.py migrates the same way).
        if !rows("PRAGMA table_info(plays)", []).contains(where: { $0.count > 1 && $0[1] == "genre" }) {
            exec("ALTER TABLE plays ADD COLUMN genre TEXT")
        }
    }

    func exec(_ sql: String) {
        var err: UnsafeMutablePointer<CChar>?
        if sqlite3_exec(handle, sql, nil, nil, &err) != SQLITE_OK {
            log("sqlite: \(String(cString: err!))")
            sqlite3_free(err)
        }
    }

    func insertPlay(_ p: Play, listened: Double, ended: Date) {
        let sql = """
            INSERT INTO plays (ts, played_at, title, artist, album, duration,
                               seconds_listened, skipped, source, persistent_id, ended_ts, genre)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, 'mac', ?, ?, ?)
            """
        var st: OpaquePointer?
        guard sqlite3_prepare_v2(handle, sql, -1, &st, nil) == SQLITE_OK else { return }
        defer { sqlite3_finalize(st) }
        let skipped = p.duration > 0 && listened < p.duration * skipFraction
        sqlite3_bind_int64(st, 1, Int64(p.start.timeIntervalSince1970))
        sqlite3_bind_text(st, 2, isoLocal.string(from: p.start), -1, SQLITE_TRANSIENT)
        sqlite3_bind_text(st, 3, p.title, -1, SQLITE_TRANSIENT)
        sqlite3_bind_text(st, 4, p.artist, -1, SQLITE_TRANSIENT)
        sqlite3_bind_text(st, 5, p.album, -1, SQLITE_TRANSIENT)
        if p.duration > 0 { sqlite3_bind_double(st, 6, p.duration) } else { sqlite3_bind_null(st, 6) }
        sqlite3_bind_double(st, 7, listened.rounded())
        sqlite3_bind_int(st, 8, skipped ? 1 : 0)
        if let pid = p.pid { sqlite3_bind_text(st, 9, pid, -1, SQLITE_TRANSIENT) } else { sqlite3_bind_null(st, 9) }
        sqlite3_bind_int64(st, 10, Int64(ended.timeIntervalSince1970))
        if let g = p.genre, !g.isEmpty { sqlite3_bind_text(st, 11, g, -1, SQLITE_TRANSIENT) } else { sqlite3_bind_null(st, 11) }
        if sqlite3_step(st) != SQLITE_DONE {
            log("insert failed: \(String(cString: sqlite3_errmsg(handle)))")
        }
    }

    func rows(_ sql: String, _ args: [Int64]) -> [[String]] {
        var st: OpaquePointer?
        guard sqlite3_prepare_v2(handle, sql, -1, &st, nil) == SQLITE_OK else { return [] }
        defer { sqlite3_finalize(st) }
        for (i, a) in args.enumerated() { sqlite3_bind_int64(st, Int32(i + 1), a) }
        var out: [[String]] = []
        while sqlite3_step(st) == SQLITE_ROW {
            out.append((0..<sqlite3_column_count(st)).map { i in
                sqlite3_column_text(st, i).map { String(cString: $0) } ?? ""
            })
        }
        return out
    }
}

// MARK: - Widget summary (same format as musicwrapped/summary.py)

func writeSummary(_ db: DB) {
    let now = Date()
    guard let week = isoCalendar.dateInterval(of: .weekOfYear, for: now) else { return }
    let start = Int64(week.start.timeIntervalSince1970)
    let end = Int64(week.end.timeIntervalSince1970)
    let listened = "CASE WHEN source = 'mac' THEN seconds_listened ELSE COALESCE(duration, seconds_listened) END"
    let tot = db.rows("SELECT COALESCE(SUM(\(listened)), 0), COUNT(*) FROM plays WHERE ts >= ? AND ts < ?", [start, end]).first ?? ["0", "0"]
    let artist = db.rows("""
        SELECT artist, COUNT(*) n FROM plays WHERE ts >= ? AND ts < ? AND COALESCE(artist, '') != ''
        GROUP BY artist ORDER BY n DESC, SUM(\(listened)) DESC LIMIT 1
        """, [start, end]).first
    let song = db.rows("""
        SELECT title, artist, COUNT(*) n, MAX(persistent_id) FROM plays WHERE ts >= ? AND ts < ?
        GROUP BY title, artist ORDER BY n DESC, SUM(\(listened)) DESC LIMIT 1
        """, [start, end]).first
    // Minutes per day, Monday first (same as musicwrapped/summary.py).
    var daily = [Double](repeating: 0, count: 7)
    for r in db.rows("SELECT (ts - ?) / 86400, SUM(\(listened)) FROM plays WHERE ts >= ? AND ts < ? GROUP BY 1", [start, start, end]) {
        if let i = Int(r[0]), i >= 0, i < 7 { daily[i] = ((Double(r[1]) ?? 0) / 6).rounded() / 10 }
    }
    // Genre as reported for the play, else the library track's (same rule as musicwrapped/stats.py).
    // The library table is created by the Python side, so it may not exist yet.
    let hasLibrary = !db.rows("SELECT 1 FROM sqlite_master WHERE type = 'table' AND name = 'library'", []).isEmpty
    let genreExpr = hasLibrary
        ? "SELECT COALESCE(NULLIF(p.genre, ''), l.genre) g FROM plays p LEFT JOIN library l ON l.persistent_id = p.persistent_id"
        : "SELECT p.genre g FROM plays p"
    let genre = db.rows("""
        SELECT g, COUNT(*) n FROM (\(genreExpr) WHERE p.ts >= ? AND p.ts < ?)
        WHERE COALESCE(g, '') != '' GROUP BY g ORDER BY n DESC, g LIMIT 1
        """, [start, end]).first
    let y = isoCalendar.component(.yearForWeekOfYear, from: now)
    let w = isoCalendar.component(.weekOfYear, from: now)
    let dayFmt = DateFormatter()
    dayFmt.dateFormat = "yyyy-MM-dd"
    var obj: [String: Any] = [
        "generated_at": isoLocal.string(from: now),
        "week": String(format: "%04d-W%02d", y, w),
        "week_start": dayFmt.string(from: week.start),
        "hours": ((Double(tot[0]) ?? 0) / 360).rounded() / 10,
        "plays": Int(tot[1]) ?? 0,
        "top_artist": NSNull(),
        "top_song": NSNull(),
        "top_genre": NSNull(),
        "daily_minutes": daily,
    ]
    if let a = artist {
        // Cover for the artist: their most-played track this week.
        let pid = db.rows("""
            SELECT persistent_id FROM plays WHERE ts >= ? AND ts < ? AND artist = '\(a[0].replacingOccurrences(of: "'", with: "''"))'
            AND persistent_id IS NOT NULL GROUP BY persistent_id ORDER BY COUNT(*) DESC LIMIT 1
            """, [start, end]).first?.first
        obj["top_artist"] = ["name": a[0], "plays": Int(a[1]) ?? 0, "pid": pid.map { $0 as Any } ?? NSNull()]
    }
    if let s = song {
        obj["top_song"] = ["title": s[0], "artist": s[1], "plays": Int(s[2]) ?? 0,
                           "pid": s[3].isEmpty ? NSNull() as Any : s[3] as Any]
    }
    if let g = genre { obj["top_genre"] = ["name": g[0], "plays": Int(g[1]) ?? 0] }
    guard let data = try? JSONSerialization.data(withJSONObject: obj, options: [.prettyPrinted, .sortedKeys]) else { return }
    let tmp = summaryPath.appendingPathExtension("tmp")
    do {
        try data.write(to: tmp)
        _ = try FileManager.default.replaceItemAt(summaryPath, withItemAt: tmp)
    } catch {
        try? FileManager.default.removeItem(at: summaryPath)
        try? FileManager.default.moveItem(at: tmp, to: summaryPath)
    }
}

// MARK: - Live weekly report

/// Runs `music-wrapped report weekly --live` after each logged play, one run at a time.
/// Plays logged while it runs are folded into a single follow-up run.
final class Refresher {
    let cmd: String?
    var running: Process?
    var again = false

    init(cmd: String?) { self.cmd = cmd }

    func trigger() {
        guard let cmd = cmd else { return }
        if running != nil {
            again = true
            return
        }
        let p = Process()
        p.executableURL = URL(fileURLWithPath: cmd)
        p.arguments = ["report", "weekly", "--live"]
        p.standardOutput = FileHandle.nullDevice
        p.standardError = FileHandle.standardError  // errors land in logger.log
        p.terminationHandler = { _ in
            DispatchQueue.main.async {
                self.running = nil
                if self.again {
                    self.again = false
                    self.trigger()
                }
            }
        }
        do {
            try p.run()
            running = p
        } catch {
            log("could not refresh the weekly report: \(error)")
        }
    }
}

// MARK: - Play tracking

struct Play: Codable {
    let key: String
    let pid: String?
    let title: String
    let artist: String
    let album: String
    var genre: String? = nil       // optional so pending.json files from older versions still decode
    let duration: Double
    let start: Date
    var listened: Double = 0       // seconds accumulated before the current playing stretch
    var playingSince: Date?        // nil while paused
    var lastPosition: Double?      // poll mode only, used to spot a repeat of the same track

    func total(at now: Date) -> Double {
        listened + (playingSince.map { now.timeIntervalSince($0) } ?? 0)
    }
}

struct Pending: Codable {
    let play: Play
    let savedAt: Date
}

final class Tracker {
    let db: DB
    let refresher: Refresher
    var current: Play?
    var wasPlayingBeforeSleep = false

    init(db: DB, refresher: Refresher) {
        self.db = db
        self.refresher = refresher
    }

    /// Handles one playerInfo payload (from a notification, or synthesized by poll mode).
    func handle(_ info: [AnyHashable: Any]) {
        let now = Date()
        let state = info["Player State"] as? String ?? ""
        if state == "Stopped" {
            finish(now)
            return
        }
        guard let incoming = makePlay(info, now: now) else { return }
        let position = (info["Player Position"] as? NSNumber)?.doubleValue

        if var cur = current, cur.key == incoming.key {
            // Same track as before: pause / resume, or a repeat of the same track.
            var repeated = false
            if let pos = position, let last = cur.lastPosition {
                repeated = pos + 5 < last && cur.total(at: now) >= minSeconds
            } else if position == nil, state == "Playing", cur.playingSince != nil, cur.duration > 0 {
                repeated = cur.total(at: now) >= cur.duration * 0.9
            }
            if repeated {
                finish(now)
                start(incoming, playing: state == "Playing", now: now, position: position)
                return
            }
            if state == "Playing", cur.playingSince == nil {
                cur.playingSince = now
            } else if state == "Paused", let since = cur.playingSince {
                cur.listened += now.timeIntervalSince(since)
                cur.playingSince = nil
            }
            cur.lastPosition = position
            current = cur
        } else {
            finish(now)
            start(incoming, playing: state == "Playing", now: now, position: position)
        }
    }

    func start(_ p: Play, playing: Bool, now: Date, position: Double?) {
        var p = p
        p.playingSince = playing ? now : nil
        p.lastPosition = position
        current = p
    }

    func makePlay(_ info: [AnyHashable: Any], now: Date) -> Play? {
        let title = info["Name"] as? String ?? ""
        let artist = info["Artist"] as? String ?? ""
        var pid: String?
        if let n = (info["PersistentID"] ?? info["Persistent ID"]) as? NSNumber {
            pid = String(format: "%016llX", UInt64(bitPattern: n.int64Value))
        } else if let s = info["PersistentID"] as? String {
            pid = s.uppercased()
        }
        if title.isEmpty && pid == nil { return nil }
        let ms = (info["Total Time"] as? NSNumber)?.doubleValue ?? 0
        return Play(key: pid ?? "\(title)|\(artist)", pid: pid, title: title, artist: artist,
                    album: info["Album"] as? String ?? "", genre: info["Genre"] as? String,
                    duration: ms / 1000, start: now)
    }

    /// Ends the current play and stores it if it was listened to long enough.
    func finish(_ now: Date) {
        guard let p = current else { return }
        current = nil
        var listened = p.total(at: now)
        if p.duration > 0 { listened = min(listened, p.duration) }
        guard listened >= minSeconds else { return }
        db.insertPlay(p, listened: listened, ended: now)
        writeSummary(db)
        refresher.trigger()
        log("play: \(p.artist) – \(p.title) (\(Int(listened))s)")
    }

    /// Saves the song in progress instead of logging it (we're being stopped; see restore()).
    func suspend(_ now: Date) {
        guard var p = current else { return }
        p.listened = p.total(at: now)
        p.playingSince = nil
        let pending = Pending(play: p, savedAt: now)
        if let data = try? JSONEncoder().encode(pending) { try? data.write(to: pendingPath, options: .atomic) }
    }

    /// Runs once at startup. `info` is what Music is doing right now (nil if it isn't running).
    func restore(_ info: [AnyHashable: Any]?, now: Date) {
        var pending: Pending?
        if let d = try? Data(contentsOf: pendingPath) {
            pending = try? JSONDecoder().decode(Pending.self, from: d)
            try? FileManager.default.removeItem(at: pendingPath)
        }
        let state = info?["Player State"] as? String ?? "Stopped"
        let incoming = state == "Stopped" ? nil : info.flatMap { makePlay($0, now: now) }
        if let p = pending, let inc = incoming, p.play.key == inc.key, now.timeIntervalSince(p.savedAt) < resumeWindow {
            var cur = p.play
            cur.playingSince = state == "Playing" ? now : nil
            current = cur
            log("resumed: \(cur.artist) – \(cur.title) (\(Int(cur.listened))s so far)")
            return
        }
        if let p = pending {
            current = p.play
            finish(p.savedAt)
        }
        if let info = info, incoming != nil {
            handle(info)
            if let cur = current { log("already playing: \(cur.artist) – \(cur.title)") }
        }
    }

    func pauseClock(_ now: Date) {
        guard var cur = current, let since = cur.playingSince else { wasPlayingBeforeSleep = false; return }
        cur.listened += now.timeIntervalSince(since)
        cur.playingSince = nil
        current = cur
        wasPlayingBeforeSleep = true
    }

    func resumeClock(_ now: Date) {
        guard wasPlayingBeforeSleep, var cur = current else { return }
        cur.playingSince = now
        current = cur
        wasPlayingBeforeSleep = false
    }
}

// MARK: - Poll mode (fallback)

let pollScript = NSAppleScript(source: """
    tell application "Music"
        set s to player state as text
        if s is "stopped" then return {s}
        set t to current track
        return {s, name of t, artist of t, album of t, duration of t, persistent ID of t, player position}
    end tell
    """)!

func musicRunning() -> Bool {
    NSWorkspace.shared.runningApplications.contains { $0.bundleIdentifier == musicBundleID }
}

/// Asks Music for its current state, shaped like a playerInfo notification. nil if Music
/// isn't running or we're not allowed to control it.
func queryMusic() -> [AnyHashable: Any]? {
    if let fake = env["MUSIC_WRAPPED_TEST_QUERY"] {
        guard let d = fake.data(using: .utf8), let o = try? JSONSerialization.jsonObject(with: d) as? [String: Any] else { return nil }
        var info: [AnyHashable: Any] = o
        if let ms = o["Total Time"] as? Double { info["Total Time"] = NSNumber(value: ms) }
        return info
    }
    guard musicRunning() else { return nil }
    var err: NSDictionary?
    let res = pollScript.executeAndReturnError(&err)
    if let err = err {
        log("could not ask Music what's playing: \(err[NSAppleScript.errorMessage] ?? err)")
        return nil
    }
    let item = { (i: Int) in res.atIndex(i)?.stringValue ?? "" }
    let state = item(1)
    var info: [AnyHashable: Any] = ["Player State": state.prefix(1).uppercased() + state.dropFirst()]
    if state != "stopped", res.numberOfItems >= 7 {
        info["Name"] = item(2)
        info["Artist"] = item(3)
        info["Album"] = item(4)
        info["Total Time"] = NSNumber(value: (Double(item(5)) ?? 0) * 1000)
        info["PersistentID"] = item(6)
        info["Player Position"] = NSNumber(value: Double(item(7)) ?? 0)
    }
    return info
}

func pollOnce(_ tracker: Tracker) {
    if let info = queryMusic() {
        heartbeat(info)
        tracker.handle(info)
    }
}

// MARK: - Heartbeat

/// Records when Music was last seen playing (written at most once a minute).
var lastHeartbeat = Date.distantPast
func heartbeat(_ info: [AnyHashable: Any]) {
    guard info["Player State"] as? String == "Playing", Date().timeIntervalSince(lastHeartbeat) > 60 else { return }
    lastHeartbeat = Date()
    let obj: [String: Any] = ["last_playing": isoLocal.string(from: lastHeartbeat),
                              "last_playing_ts": Int(lastHeartbeat.timeIntervalSince1970)]
    if let d = try? JSONSerialization.data(withJSONObject: obj) { try? d.write(to: heartbeatPath, options: .atomic) }
}

// MARK: - Main

/// Restores the saved play and records the heartbeat if Music is already playing.
func startup(_ info: [AnyHashable: Any]?) {
    if let info = info { heartbeat(info) }
    tracker.restore(info, now: Date())
}

let args = CommandLine.arguments
let dnc = DistributedNotificationCenter.default()

// --post '<json>': post one playerInfo-shaped notification (tests only; uses MUSIC_WRAPPED_NOTIFICATION).
if args.count >= 3, args[1] == "--post" {
    guard env["MUSIC_WRAPPED_NOTIFICATION"] != nil else {
        print("--post needs MUSIC_WRAPPED_NOTIFICATION, so it can never fake real Music events")
        exit(1)
    }
    let o = (try? JSONSerialization.jsonObject(with: Data(args[2].utf8)) as? [String: Any]) ?? [:]
    var info: [AnyHashable: Any] = [:]
    for (k, v) in o {
        if k == "PersistentID", let n = v as? NSNumber { info[k] = NSNumber(value: n.int64Value) } else { info[k] = v }
    }
    dnc.postNotificationName(notificationName, object: nil, userInfo: info, deliverImmediately: true)
    exit(0)
}

if args.count >= 2, args[1] == "--probe" {
    let secs = args.count >= 3 ? Double(args[2]) ?? 60 : 60
    setvbuf(stdout, nil, _IOLBF, 0)  // print events live, even when piped
    var count = 0
    print("Listening for com.apple.Music.playerInfo for \(Int(secs)) s. Play, pause or skip a song in Music now…")
    dnc.addObserver(forName: notificationName, object: nil, queue: .main) { n in
        count += 1
        let info = n.userInfo ?? [:]
        let pid = (info["PersistentID"] as? NSNumber).map { String(format: "%016llX", UInt64(bitPattern: $0.int64Value)) } ?? "-"
        print("[\(count)] \(info["Player State"] ?? "?") | \(info["Artist"] ?? "") – \(info["Name"] ?? "") | pid \(pid) | keys: \(info.keys.map { "\($0)" }.sorted().joined(separator: ", "))")
    }
    RunLoop.main.run(until: Date().addingTimeInterval(secs))
    print("RESULT: \(count) notification(s) received")
    exit(count > 0 ? 0 : 2)
}

let mode: String = {
    guard let d = try? Data(contentsOf: configPath),
          let o = try? JSONSerialization.jsonObject(with: d) as? [String: Any] else { return "notifications" }
    return o["mode"] as? String ?? "notifications"
}()

let refreshCmd: String? = args.firstIndex(of: "--refresh-cmd").flatMap { i in i + 1 < args.count ? args[i + 1] : nil }
let db = DB()
let tracker = Tracker(db: db, refresher: Refresher(cmd: refreshCmd))
let ws = NSWorkspace.shared.notificationCenter
var pollTimer: Timer?

func startPolling() {
    guard pollTimer == nil else { return }
    pollOnce(tracker)
    pollTimer = Timer.scheduledTimer(withTimeInterval: pollInterval, repeats: true) { _ in pollOnce(tracker) }
    pollTimer?.tolerance = 5
}

func stopPolling() {
    pollTimer?.invalidate()
    pollTimer = nil
}

if mode == "poll" {
    log("starting in poll mode (every \(Int(pollInterval)) s while Music is running)")
    startup(queryMusic())
    if musicRunning() { startPolling() }
    ws.addObserver(forName: NSWorkspace.didLaunchApplicationNotification, object: nil, queue: .main) { n in
        if (n.userInfo?[NSWorkspace.applicationUserInfoKey] as? NSRunningApplication)?.bundleIdentifier == musicBundleID {
            startPolling()
        }
    }
} else {
    log("starting in notification mode")
    startup(queryMusic())
    dnc.addObserver(forName: notificationName, object: nil, queue: .main) { n in
        let info = n.userInfo ?? [:]
        heartbeat(info)
        tracker.handle(info)
    }
}

ws.addObserver(forName: NSWorkspace.didTerminateApplicationNotification, object: nil, queue: .main) { n in
    if (n.userInfo?[NSWorkspace.applicationUserInfoKey] as? NSRunningApplication)?.bundleIdentifier == musicBundleID {
        stopPolling()
        tracker.finish(Date())
    }
}
ws.addObserver(forName: NSWorkspace.willSleepNotification, object: nil, queue: .main) { _ in tracker.pauseClock(Date()) }
ws.addObserver(forName: NSWorkspace.didWakeNotification, object: nil, queue: .main) { _ in tracker.resumeClock(Date()) }

// Save the play in progress when launchd stops us (logout / shutdown / restart).
signal(SIGTERM, SIG_IGN)
signal(SIGINT, SIG_IGN)
var signalSources: [DispatchSourceSignal] = []
for sig in [SIGTERM, SIGINT] {
    let src = DispatchSource.makeSignalSource(signal: sig, queue: .main)
    src.setEventHandler {
        tracker.suspend(Date())
        exit(0)
    }
    src.resume()
    signalSources.append(src)
}

RunLoop.main.run()
