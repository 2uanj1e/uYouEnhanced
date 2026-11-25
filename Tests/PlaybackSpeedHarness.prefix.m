#import <Foundation/Foundation.h>
#import <dispatch/dispatch.h>
#import <objc/message.h>
#import <objc/runtime.h>
#import <math.h>
#import <string.h>
#define CODEX_PLAYBACK_FIXES 1
#define UIControlStateNormal 0
@interface UIView : NSObject @end
@implementation UIView @end
@interface UIControl : UIView
@property BOOL enabled;
@end
@implementation UIControl @end
@interface UIButton : UIControl
@property(copy) NSString *title;
- (void)setTitle:(NSString *)title forState:(NSUInteger)state;
@end
@implementation UIButton
- (void)setTitle:(NSString *)title forState:(NSUInteger)state { self.title=title; }
@end
@interface Wrapper : NSObject
@property(strong) UIButton *button;
@end
@implementation Wrapper
- (id)init { if ((self=[super init])) self.button=[UIButton new]; return self; }
@end
@interface YTPlayerOverlayManager : NSObject
@property float engineRate;
@property NSUInteger writes;
@property NSUInteger nilControllerWrites;
- (id)varispeedController;
- (float)currentPlaybackRateForVarispeedSwitchController:(id)controller;
- (void)varispeedSwitchController:(id)controller didSelectRate:(float)rate;
@end
@implementation YTPlayerOverlayManager
- (id)varispeedController { return nil; }
- (float)currentPlaybackRateForVarispeedSwitchController:(id)controller { return self.engineRate; }
- (void)varispeedSwitchController:(id)controller didSelectRate:(float)rate {
 self.engineRate=rate; self.writes++; if (!controller) self.nilControllerWrites++;
}
@end
@interface YTMainAppVideoPlayerOverlayViewController : NSObject
@property(strong) id delegate;
@property NSUInteger menuCount;
- (void)didPressVarispeed:(id)sender;
@end
@implementation YTMainAppVideoPlayerOverlayViewController
- (void)didPressVarispeed:(id)sender { self.menuCount++; }
@end
@interface YTMainAppControlsOverlayView : UIView
@property(strong) id eventsDelegate;
@property(strong) id ancestorOverlay;
@property(strong) Wrapper *resetPlaybackRateButtonView;
@property(strong) Wrapper *decreasePlaybackRateButtonView;
@property(strong) Wrapper *increasePlaybackRateButtonView;
@property NSUInteger legacyCalls;
- (void)didPressDecreasePlaybackRate;
- (void)didPressIncreasePlaybackRate;
- (void)didPressResetPlaybackRate;
- (void)updatePlaybackRate;
- (id)_viewControllerForAncestor;
@end
@implementation YTMainAppControlsOverlayView
- (id)init { if ((self=[super init])) { self.resetPlaybackRateButtonView=[Wrapper new];self.decreasePlaybackRateButtonView=[Wrapper new];self.increasePlaybackRateButtonView=[Wrapper new]; }return self; }
- (void)didPressDecreasePlaybackRate { self.legacyCalls++; }
- (void)didPressIncreasePlaybackRate { self.legacyCalls++; }
- (void)didPressResetPlaybackRate { self.legacyCalls++; }
- (void)updatePlaybackRate { self.legacyCalls++; }
- (id)_viewControllerForAncestor { return self.ancestorOverlay; }
@end

static double CXWrongReadRate(id self, SEL selector, id controller) { return 4.0; }
static void CXWrongWriteRate(id self, SEL selector, id controller, double rate) {}
static id CXBadABIManager(const char *name, BOOL wrongWrite) {
 Class cls = objc_allocateClassPair([YTPlayerOverlayManager class], name, 0);
 if (!cls) return nil;
 BOOL added = wrongWrite
   ? class_addMethod(cls, @selector(varispeedSwitchController:didSelectRate:), (IMP)CXWrongWriteRate, "v@:@d")
   : class_addMethod(cls, @selector(currentPlaybackRateForVarispeedSwitchController:), (IMP)CXWrongReadRate, "d@:@");
 if (!added) return nil;
 objc_registerClassPair(cls);
 return [cls new];
}
