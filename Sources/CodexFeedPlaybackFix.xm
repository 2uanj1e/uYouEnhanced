#import <Foundation/Foundation.h>

#if CODEX_PLAYBACK_FIXES

// Verified against YouTube 21.14.4 Objective-C metadata:
//   -processInceptionPrepPause  v16@0:8
//   -pauseInlinePlayback        v16@0:8
// Keep feed previews enabled. Only reinforce the hand-off from an inline
// preview to the watch-detail player so the old inline audio cannot survive
// beside the newly activated main player.
@interface YTInlineMutedPlaybackWatchController : NSObject
- (void)pauseInlinePlayback;
@end

%hook YTInlineMutedPlaybackWatchController

- (void)processInceptionPrepPause {
    %orig;

    // This lifecycle callback belongs to the inline controller and runs while
    // preparing the inline -> watch transition. It does not hook the main
    // player, app backgrounding, or Picture in Picture paths.
    [self pauseInlinePlayback];
}

%end

#endif
