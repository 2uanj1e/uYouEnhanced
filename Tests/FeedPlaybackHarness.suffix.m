@end
#define CHECK(x) do { if (!(x)) { fprintf(stderr,"FAIL line %d: %s\n",__LINE__,#x); return 1; } } while(0)
int main(void) { @autoreleasepool {
 YTInlineMutedPlaybackWatchController *a=[YTInlineMutedPlaybackWatchController new], *b=[YTInlineMutedPlaybackWatchController new];
 CHECK(a.playing && b.playing);
 [a processInceptionPrepPause];
 CHECK(a.originalCalls==1 && a.pauseCalls==1 && a.suspendCalls==1);
 CHECK(([a.events isEqual:@[@"original",@"pauseInline",@"suspend"]]));
 CHECK(!a.playing && b.playing && b.originalCalls==0 && b.pauseCalls==0 && b.suspendCalls==0);
 [b processInceptionPrepPause];
 CHECK(!b.playing && b.originalCalls==1 && b.pauseCalls==1 && b.suspendCalls==1);
 puts("PASS: current-source feed handoff; original first; pause/suspend on same inline controller; other preview unaffected");
 return 0;
} }
