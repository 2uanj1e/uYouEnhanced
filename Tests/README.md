# Local playback regression tests

Run from the repository root on macOS with Python 3 and Xcode Command Line Tools:

```sh
python3 Tests/run-playback-regression.py
# Optional local command/output record:
python3 Tests/run-playback-regression.py --report /path/to/playback-regression.json
```

Every run reads the **current production** `Sources/CodexPlaybackSpeedFix.xm`
and `Sources/CodexFeedPlaybackFix.xm`. It generates temporary Objective-C tests
using the adjacent Foundation-only prefix/suffix scaffolding, compiles them,
runs them, and removes the temporary build files. No stale copy of the speed or
feed implementation is maintained inside the test scaffolding.

Transformations are intentionally small and checked:

- Speed: substitute the UIKit import with narrow Foundation doubles and translate
  the Logos `%ctor` wrapper into an Objective-C constructor.
- Feed: take the current `YTInlineMutedPlaybackWatchController` hook body and
  translate `%orig` into a recorded original-method test double.

Checks cover per-overlay speed isolation, external/native-menu rate changes,
reset and stepping boundaries, extended-rate direction, nil varispeed controller,
ancestor lookup, rejection of mismatched float/double method signatures, and
original-first feed handoff confined to its own inline controller. Separate
source checks ensure the legacy conflicting speed group is gated off and only
the permanent NSBundle spoof was removed, while sideload/keychain hooks remain.

These are **control-flow/ABI-guard tests with doubles**. They do not verify the
actual class/method ABI or implementation in a new YouTube executable. Those
must be checked independently against that exact version. They also do not play
video, sign into Google, install an app, or prove device behavior.

Optional JSON reports contain literal local compile/run paths. Review those
paths before publishing a report. Tests make no network requests and change no
application or system preferences.
