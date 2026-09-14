#import <UIKit/UIKit.h>
#import <objc/message.h>
#import <objc/runtime.h>
#import <math.h>
#import <string.h>

#if CODEX_PLAYBACK_FIXES

// Verified against YouTube 21.14.4 and uYou 3.0.4. uYou's centre buttons
// use a process-wide last player and its legacy varispeedController._options.
// Resolve only the tapped control's own overlay and use the native delegate
// callback, whose rate argument is float (the overlay's display getter is double).
static BOOL CXSig(id object, SEL selector, const char *result, NSUInteger argc) {
    if (!object || ![object respondsToSelector:selector]) return NO;
    NSMethodSignature *sig = [object methodSignatureForSelector:selector];
    return sig && sig.numberOfArguments == argc && strcmp(sig.methodReturnType, result) == 0;
}

static id CXObject(id object, NSString *name) {
    SEL selector = NSSelectorFromString(name);
    if (!CXSig(object, selector, "@", 2)) return nil;
    return ((id (*)(id, SEL))objc_msgSend)(object, selector);
}

static id CXOverlay(id controls) {
    if (![controls isKindOfClass:[UIView class]]) return nil;
    Class cls = NSClassFromString(@"YTMainAppVideoPlayerOverlayViewController");
    id overlay = CXObject(controls, @"eventsDelegate");
    if (cls && [overlay isKindOfClass:cls]) return overlay;
    // Supported YouTube UIView helper; confined to this view's responder chain.
    overlay = CXObject(controls, @"_viewControllerForAncestor");
    return cls && [overlay isKindOfClass:cls] ? overlay : nil;
}

static id CXManager(id overlay) {
    id manager = CXObject(overlay, @"delegate");
    Class cls = NSClassFromString(@"YTPlayerOverlayManager");
    if (!cls || ![manager isKindOfClass:cls]) return nil;
    SEL select = NSSelectorFromString(@"varispeedSwitchController:didSelectRate:");
    SEL read = NSSelectorFromString(@"currentPlaybackRateForVarispeedSwitchController:");
    if (!CXSig(manager, select, "v", 4) || !CXSig(manager, read, "f", 3)) return nil;
    NSMethodSignature *writeSig = [manager methodSignatureForSelector:select];
    NSMethodSignature *readSig = [manager methodSignatureForSelector:read];
    if (strcmp([writeSig getArgumentTypeAtIndex:2], "@") ||
        strcmp([writeSig getArgumentTypeAtIndex:3], "f") ||
        strcmp([readSig getArgumentTypeAtIndex:2], "@")) return nil;
    return manager;
}

static float CXReadRate(id manager) {
    id varispeed = CXObject(manager, @"varispeedController");
    return ((float (*)(id, SEL, id))objc_msgSend)(manager,
        NSSelectorFromString(@"currentPlaybackRateForVarispeedSwitchController:"), varispeed);
}

static void CXUpdateLabel(id controls, float rate) {
    if (!isfinite(rate) || rate <= 0) return;
    id wrapper = CXObject(controls, @"resetPlaybackRateButtonView");
    id button = CXObject(wrapper, @"button");
    if ([button isKindOfClass:[UIButton class]]) {
        NSNumberFormatter *formatter = [NSNumberFormatter new];
        formatter.minimumFractionDigits = 0;
        formatter.maximumFractionDigits = 2;
        NSString *label = [[formatter stringFromNumber:@(rate)] stringByAppendingString:@"x"];
        [(UIButton *)button setTitle:label forState:UIControlStateNormal];
    }
    for (NSString *name in @[@"decreasePlaybackRateButtonView", @"increasePlaybackRateButtonView"]) {
        id stepButton = CXObject(CXObject(controls, name), @"button");
        if ([stepButton isKindOfClass:[UIControl class]]) {
            [(UIControl *)stepButton setEnabled:[name hasPrefix:@"decrease"] ? rate != 0.25f : rate != 2.0f];
        }
    }
}

static void CXNativeSpeedMenu(id overlay, id controls) {
    SEL selector = NSSelectorFromString(@"didPressVarispeed:");
    if (CXSig(overlay, selector, "v", 3))
        ((void (*)(id, SEL, id))objc_msgSend)(overlay, selector, controls);
}

static void CXChangeRate(id controls, int direction) {
    id overlay = CXOverlay(controls);
    id manager = CXManager(overlay);
    if (!manager) { CXNativeSpeedMenu(overlay, controls); return; }
    float current = CXReadRate(manager);
    if (!isfinite(current) || current <= 0) { CXNativeSpeedMenu(overlay, controls); return; }
    // 0 resets explicitly to 1x. A subsequent +/- starts from the engine's rate,
    // including any change made through YouTube's original settings menu.
    // Preserve direction after the original menu selects an extended rate.
    // At 3x, minus selects 2.75x; plus presents the original menu instead of
    // unexpectedly dropping to 2x. Existing rates below .25x are handled alike.
    if ((direction > 0 && current > 2.0f) || (direction < 0 && current < 0.25f)) {
        CXNativeSpeedMenu(overlay, controls);
        return;
    }
    float rate = 1.0f;
    if (direction > 0) rate = fminf(2.0f, current + 0.25f);
    if (direction < 0) rate = fmaxf(0.25f, current - 0.25f);
    id varispeed = CXObject(manager, @"varispeedController");
    ((void (*)(id, SEL, id, float))objc_msgSend)(manager,
        NSSelectorFromString(@"varispeedSwitchController:didSelectRate:"), varispeed, rate);
    CXUpdateLabel(controls, rate);
}

static void CXDecrease(id self, SEL _cmd) { CXChangeRate(self, -1); }
static void CXIncrease(id self, SEL _cmd) { CXChangeRate(self, 1); }
static void CXReset(id self, SEL _cmd) { CXChangeRate(self, 0); }
static void CXUpdate(id self, SEL _cmd) {
    id manager = CXManager(CXOverlay(self));
    if (manager) CXUpdateLabel(self, CXReadRate(manager));
}

static void CXInstallSpeedBridge(void) {
    Class cls = NSClassFromString(@"YTMainAppControlsOverlayView");
    if (!cls) return;
    struct { const char *name; IMP replacement; } methods[] = {
        {"didPressDecreasePlaybackRate", (IMP)CXDecrease},
        {"didPressIncreasePlaybackRate", (IMP)CXIncrease},
        {"didPressResetPlaybackRate", (IMP)CXReset},
        {"updatePlaybackRate", (IMP)CXUpdate},
    };
    for (NSUInteger i = 0; i < sizeof(methods) / sizeof(methods[0]); ++i) {
        SEL selector = sel_registerName(methods[i].name);
        Method method = class_getInstanceMethod(cls, selector);
        if (!method) continue; // showPlaybackRate may intentionally be off.
        NSMethodSignature *sig = [NSMethodSignature signatureWithObjCTypes:method_getTypeEncoding(method)];
        if (sig.numberOfArguments == 2 && strcmp(sig.methodReturnType, "v") == 0)
            class_replaceMethod(cls, selector, methods[i].replacement, method_getTypeEncoding(method));
    }
}

%ctor {
    // All image constructors (including uYou's class_addMethod calls) finish
    // before this main-queue block executes. No last-player global is captured.
    dispatch_async(dispatch_get_main_queue(), ^{ CXInstallSpeedBridge(); });
}

#endif
