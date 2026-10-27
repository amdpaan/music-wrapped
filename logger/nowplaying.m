// music-wrapped-nowplaying.dylib: reports what's playing in apps other than Music (e.g. YT Music,
// a browser) to the logger, one JSON line per change on stdout.
//
// Since macOS 15.4 only Apple-signed processes may read Now Playing (MediaRemote), so the logger
// doesn't call it itself: it runs /usr/bin/perl, which loads this library and calls mw_stream()
// (the same trick as the open-source mediaremote-adapter). It only reads; it never controls playback.
//
//   /usr/bin/perl -e '<stub, see logger/main.swift>' music-wrapped-nowplaying.dylib
//
// Lines: {"state":"Playing"|"Paused","title","artist","album","duration","elapsed","art"?} or
// {"state":"Stopped"} when nothing (or only the Music app) is playing. "art" (base64) is sent once
// per cover. The library exits when the logger goes away.

#import <Foundation/Foundation.h>
#include <dlfcn.h>
#include <libproc.h>
#include <unistd.h>

typedef void (*GetInfoFn)(dispatch_queue_t, void (^)(NSDictionary *));
typedef void (*GetPIDFn)(dispatch_queue_t, void (^)(int));
typedef void (*IsPlayingFn)(dispatch_queue_t, void (^)(BOOL));
typedef void (*RegisterFn)(dispatch_queue_t);

static GetInfoFn getInfo;
static GetPIDFn getPID;
static IsPlayingFn getIsPlaying;
static NSString *lastKey;          // state + track, to send only changes
static double lastElapsed, lastAt; // to spot seeks and repeats of the same track
static NSString *lastArt;          // artwork identifier already sent

static void emit(NSDictionary *obj) {
    NSData *d = [NSJSONSerialization dataWithJSONObject:obj options:0 error:nil];
    if (!d) return;
    fwrite(d.bytes, 1, d.length, stdout);
    fputc('\n', stdout);
    fflush(stdout);
}

static void stopped(void) {
    if ([lastKey isEqualToString:@"Stopped"]) return;
    lastKey = @"Stopped";
    emit(@{@"state": @"Stopped"});
}

static BOOL isMusicApp(int pid) {
    char path[PROC_PIDPATHINFO_MAXSIZE];
    if (pid <= 0 || proc_pidpath(pid, path, sizeof path) <= 0) return NO;
    return strstr(path, "/Music.app/") != NULL;  // tracked by the logger's own Music listener
}

static NSString *str(id v) { return [v isKindOfClass:[NSString class]] ? v : @""; }
static double num(id v) { return [v isKindOfClass:[NSNumber class]] ? [v doubleValue] : 0; }

static void report(NSDictionary *info, BOOL playing) {
    NSString *title = str(info[@"kMRMediaRemoteNowPlayingInfoTitle"]);
    if (title.length == 0) return stopped();
    NSString *artist = str(info[@"kMRMediaRemoteNowPlayingInfoArtist"]);
    NSString *album = str(info[@"kMRMediaRemoteNowPlayingInfoAlbum"]);
    double duration = num(info[@"kMRMediaRemoteNowPlayingInfoDuration"]);
    double rate = num(info[@"kMRMediaRemoteNowPlayingInfoPlaybackRate"]);
    // Elapsed is given as of the info's timestamp; bring it up to now.
    double elapsed = num(info[@"kMRMediaRemoteNowPlayingInfoElapsedTime"]);
    NSDate *stamp = info[@"kMRMediaRemoteNowPlayingInfoTimestamp"];
    if (playing && [stamp isKindOfClass:[NSDate class]]) elapsed += -[stamp timeIntervalSinceNow] * (rate > 0 ? rate : 1);
    NSString *state = playing ? @"Playing" : @"Paused";
    NSString *key = [NSString stringWithFormat:@"%@\x1f%@\x1f%@\x1f%@\x1f%.0f", state, title, artist, album, duration];

    double now = [NSDate date].timeIntervalSince1970;
    double expected = lastElapsed + ([lastKey hasPrefix:@"Playing"] ? now - lastAt : 0);
    BOOL jumped = fabs(elapsed - expected) > 5;
    lastElapsed = elapsed;
    lastAt = now;

    NSString *artID = str(info[@"kMRMediaRemoteNowPlayingInfoArtworkIdentifier"]);
    NSData *art = info[@"kMRMediaRemoteNowPlayingInfoArtworkData"];
    BOOL newArt = [art isKindOfClass:[NSData class]] && art.length > 0 &&
                  ![(artID.length ? artID : key) isEqualToString:lastArt ?: @""];
    if ([key isEqualToString:lastKey] && !jumped && !newArt) return;
    lastKey = key;

    NSMutableDictionary *o = [@{@"state": state, @"title": title, @"artist": artist, @"album": album,
                                @"duration": @(duration), @"elapsed": @(round(elapsed * 10) / 10)} mutableCopy];
    if (newArt) {
        lastArt = artID.length ? artID : key;
        o[@"art"] = [art base64EncodedStringWithOptions:0];
    }
    emit(o);
}

static void refresh(void) {
    getPID(dispatch_get_main_queue(), ^(int pid) {
        if (pid <= 0 || isMusicApp(pid)) return stopped();
        getIsPlaying(dispatch_get_main_queue(), ^(BOOL playing) {
            getInfo(dispatch_get_main_queue(), ^(NSDictionary *info) {
                if (!info) return stopped();
                report(info, playing);
            });
        });
    });
}

// Called from perl as an XSUB; the two arguments (perl interpreter, CV) are ignored. Never returns.
void mw_stream(void *unused1, void *unused2) {
    void *mr = dlopen("/System/Library/PrivateFrameworks/MediaRemote.framework/MediaRemote", RTLD_NOW);
    getInfo = mr ? (GetInfoFn)dlsym(mr, "MRMediaRemoteGetNowPlayingInfo") : NULL;
    getPID = mr ? (GetPIDFn)dlsym(mr, "MRMediaRemoteGetNowPlayingApplicationPID") : NULL;
    getIsPlaying = mr ? (IsPlayingFn)dlsym(mr, "MRMediaRemoteGetNowPlayingApplicationIsPlaying") : NULL;
    RegisterFn reg = mr ? (RegisterFn)dlsym(mr, "MRMediaRemoteRegisterForNowPlayingNotifications") : NULL;
    if (!getInfo || !getPID || !getIsPlaying || !reg) {
        fprintf(stderr, "nowplaying: MediaRemote is not available\n");
        exit(3);
    }
    reg(dispatch_get_main_queue());
    for (NSString *name in @[@"kMRMediaRemoteNowPlayingInfoDidChangeNotification",
                             @"kMRMediaRemoteNowPlayingApplicationIsPlayingDidChangeNotification",
                             @"kMRMediaRemoteNowPlayingApplicationDidChangeNotification"]) {
        [[NSNotificationCenter defaultCenter] addObserverForName:name object:nil queue:nil
                                                      usingBlock:^(NSNotification *n) { refresh(); }];
    }
    pid_t parent = getppid();
    refresh();
    // A slow safety check in case a notification is missed, and exit with the logger.
    dispatch_source_t t = dispatch_source_create(DISPATCH_SOURCE_TYPE_TIMER, 0, 0, dispatch_get_main_queue());
    dispatch_source_set_timer(t, dispatch_time(DISPATCH_TIME_NOW, 15 * NSEC_PER_SEC), 15 * NSEC_PER_SEC, 5 * NSEC_PER_SEC);
    dispatch_source_set_event_handler(t, ^{
        if (getppid() != parent) exit(0);
        refresh();
    });
    dispatch_resume(t);
    CFRunLoopRun();
    exit(0);
}
