#define CHECK(x) do { if (!(x)) { fprintf(stderr,"FAIL line %d: %s\n",__LINE__,#x); return 1; } } while(0)
int main(void) { @autoreleasepool {
 CXInstallSpeedBridge();
 YTPlayerOverlayManager *a=[YTPlayerOverlayManager new], *b=[YTPlayerOverlayManager new];a.engineRate=1;b.engineRate=.5;
 YTMainAppVideoPlayerOverlayViewController *oa=[YTMainAppVideoPlayerOverlayViewController new], *ob=[YTMainAppVideoPlayerOverlayViewController new];oa.delegate=a;ob.delegate=b;
 YTMainAppControlsOverlayView *ca=[YTMainAppControlsOverlayView new], *cb=[YTMainAppControlsOverlayView new];ca.eventsDelegate=oa;cb.eventsDelegate=ob;
 [ca didPressIncreasePlaybackRate]; CHECK(a.engineRate==1.25f && b.engineRate==.5f); CHECK([ca.resetPlaybackRateButtonView.button.title isEqual:@"1.25x"]);
 [cb didPressDecreasePlaybackRate]; CHECK(b.engineRate==.25f && a.engineRate==1.25f);
 [cb didPressDecreasePlaybackRate];CHECK(b.engineRate==.25f);
 [ca didPressResetPlaybackRate]; CHECK(a.engineRate==1.f);
 a.engineRate=1.75f; [ca didPressDecreasePlaybackRate];CHECK(a.engineRate==1.5f);
 a.engineRate=2;[ca didPressIncreasePlaybackRate];CHECK(a.engineRate==2);
 a.engineRate=3;[ca didPressDecreasePlaybackRate];CHECK(a.engineRate==2.75f);
 [ca didPressIncreasePlaybackRate]; CHECK(a.engineRate==2.75f && oa.menuCount==1);
 [ca didPressResetPlaybackRate];CHECK(a.engineRate==1);
 a.engineRate=NAN;NSUInteger n=a.writes;[ca didPressIncreasePlaybackRate];CHECK(a.writes==n && oa.menuCount==2);
 oa.delegate=[NSObject new];[ca didPressIncreasePlaybackRate];CHECK(a.writes==n && oa.menuCount==3);
 ca.eventsDelegate=nil;[ca didPressIncreasePlaybackRate];CHECK(a.writes==n && b.engineRate==.25f);
 CHECK(ca.legacyCalls==0 && cb.legacyCalls==0);CHECK(a.nilControllerWrites==a.writes);
 // The fallback is scoped to this view's ancestor controller, never a last player.
 oa.delegate=a;ca.ancestorOverlay=oa;a.engineRate=1;
 [ca didPressIncreasePlaybackRate];CHECK(a.engineRate==1.25f && b.engineRate==.25f);
 ca.eventsDelegate=oa;ca.ancestorOverlay=nil;
 a.engineRate=2;[ca updatePlaybackRate];CHECK(!ca.increasePlaybackRateButtonView.button.enabled);
 a.engineRate=.25f;[ca updatePlaybackRate];CHECK(!ca.decreasePlaybackRateButtonView.button.enabled);
 [ca didPressResetPlaybackRate];CHECK(a.engineRate==1.f && ca.increasePlaybackRateButtonView.button.enabled && ca.decreasePlaybackRateButtonView.button.enabled);
 // A same-family manager with double instead of float ABI must fail closed to menu.
 NSUInteger menus=oa.menuCount;
 id badRead=CXBadABIManager("CXTestWrongReadManager",NO);CHECK(badRead!=nil);
 oa.delegate=badRead;[ca didPressIncreasePlaybackRate];CHECK(oa.menuCount==menus+1);
 id badWrite=CXBadABIManager("CXTestWrongWriteManager",YES);CHECK(badWrite!=nil);
 oa.delegate=badWrite;[ca didPressDecreasePlaybackRate];CHECK(oa.menuCount==menus+2);
 CHECK(ca.legacyCalls==0 && cb.legacyCalls==0);
 puts("PASS: current-source bridge; per-overlay isolation; native menu changes; nil varispeed; bounds/reset; 3x direction; ancestor fallback; float ABI guards; no legacy callback");
 return 0;
} }
