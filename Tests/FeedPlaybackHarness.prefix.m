#import <Foundation/Foundation.h>

@interface YTInlineMutedPlaybackWatchController : NSObject
@property NSUInteger originalCalls;
@property NSUInteger pauseCalls;
@property NSUInteger suspendCalls;
@property BOOL playing;
@property(strong) NSMutableArray<NSString *> *events;
- (void)processInceptionPrepPause;
- (void)cx_test_originalProcessInceptionPrepPause;
- (void)pauseInlinePlayback;
- (void)suspendPlayback;
@end
@implementation YTInlineMutedPlaybackWatchController
- (id)init { if ((self=[super init])) { self.playing=YES;self.events=[NSMutableArray new]; }return self; }
- (void)cx_test_originalProcessInceptionPrepPause { self.originalCalls++;[self.events addObject:@"original"]; }
- (void)pauseInlinePlayback { self.pauseCalls++;[self.events addObject:@"pauseInline"];[self suspendPlayback]; }
- (void)suspendPlayback { self.suspendCalls++;[self.events addObject:@"suspend"];self.playing=NO; }
