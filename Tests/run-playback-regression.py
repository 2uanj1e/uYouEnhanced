#!/usr/bin/env python3
"""Compile local Foundation tests from the actual current production hook sources.

This script does not install apps, load YouTube, contact a network, or change
preferences. UIKit/YouTube classes are narrow test doubles, not device tests.
"""
import argparse
import hashlib
import json
from pathlib import Path
import re
import subprocess
import tempfile

ROOT = Path(__file__).resolve().parents[1]
parser = argparse.ArgumentParser(description=__doc__)
parser.add_argument('--report', type=Path, help='Optional JSON result path; may contain local command paths.')
args = parser.parse_args()
record = {'scope': 'Foundation doubles; no iPhone playback/login/refresh claim', 'tests': [], 'source_checks': {}}


def sha(data):
    return hashlib.sha256(data).hexdigest()


def execute(argv):
    p = subprocess.run([str(a) for a in argv], capture_output=True, text=True, timeout=60)
    result = {'command': [str(a) for a in argv], 'stdout': p.stdout, 'stderr': p.stderr, 'exit_status': p.returncode}
    if p.returncode:
        raise RuntimeError(json.dumps(result, ensure_ascii=False, indent=2))
    return result


speed_path = ROOT / 'Sources/CodexPlaybackSpeedFix.xm'
speed = speed_path.read_text()
assert speed.count('#import <UIKit/UIKit.h>') == 1
assert speed.count('%ctor {') == 1
speed_c = speed.replace('#import <UIKit/UIKit.h>', '', 1).replace(
    '%ctor {', '__attribute__((constructor)) static void CXTestConstructor(void) {', 1)
assert not re.search(r'^\s*%(?:hook|group|end|ctor|init|orig)', speed_c, re.MULTILINE)
speed_test = ((ROOT / 'Tests/PlaybackSpeedHarness.prefix.m').read_text() + '\n' + speed_c + '\n' +
              (ROOT / 'Tests/PlaybackSpeedHarness.suffix.m').read_text())

feed_path = ROOT / 'Sources/CodexFeedPlaybackFix.xm'
feed = feed_path.read_text()
# Extract only the real production hook body; the wrapper is the Foundation test class.
match = re.search(r'%hook\s+YTInlineMutedPlaybackWatchController\s*\n(.*?)\n%end', feed, re.DOTALL)
assert match is not None
feed_hook = match.group(1)
assert feed_hook.count('%orig;') == 1
assert feed_hook.count('processInceptionPrepPause') == 1
feed_c = feed_hook.replace('%orig;', '[self cx_test_originalProcessInceptionPrepPause];', 1)
assert not re.search(r'^\s*%', feed_c, re.MULTILINE)
feed_test = ((ROOT / 'Tests/FeedPlaybackHarness.prefix.m').read_text() + '\n' + feed_c + '\n' +
             (ROOT / 'Tests/FeedPlaybackHarness.suffix.m').read_text())

patches = (ROOT / 'Sources/uYouPatches.xm').read_text()
assert 'if (speedFixesSafe && !CODEX_PLAYBACK_FIXES)' in patches
login_source = (ROOT / 'Sources/uYouPlusPatches.xm').read_text()
assert not re.search(r'%hook\s+NSBundle\b', login_source)
assert '%init(gPatches);' in login_source and '%init(gSideloadingPatches);' in login_source
assert '%hook SSOKeychainHelper' in login_source and '%hook GULKeychainStorage' in login_source
for path in ROOT.joinpath('Sources').iterdir():
    if path.is_file() and path.suffix in ('.h', '.xm', '.m', '.x'):
        assert 'kGoogleSignInPatch' not in path.read_text(), str(path)
record['source_checks'] = {
    'legacy_speed_group_disabled_when_new_bridge_enabled': True,
    'permanent_NSBundle_spoof_removed_from_uYouPlusPatches': True,
    'stale_google_signin_setting_key_removed': True,
    'other_patch_groups_and_keychain_hooks_retained': True,
}

with tempfile.TemporaryDirectory(prefix='uyou-playback-regression-') as temp:
    temp = Path(temp)
    for name, production, generated in [('speed', speed_path, speed_test), ('feed', feed_path, feed_test)]:
        source = temp / (name + '.m')
        binary = temp / name
        source.write_text(generated)
        compile_result = execute(['xcrun', 'clang', '-fobjc-arc', '-framework', 'Foundation', source, '-o', binary])
        run_result = execute([binary])
        record['tests'].append({
            'name': name,
            'production_source': str(production.relative_to(ROOT)),
            'production_sha256': sha(production.read_bytes()),
            'generated_harness_sha256': sha(source.read_bytes()),
            'generated_from_current_source': True,
            'compile': compile_result,
            'run': run_result,
        })
record['result'] = 'PASS'
if args.report:
    args.report.parent.mkdir(parents=True, exist_ok=True)
    args.report.write_text(json.dumps(record, ensure_ascii=False, indent=2) + '\n')
    assert json.loads(args.report.read_text())['result'] == 'PASS'
print(json.dumps({'result': record['result'], 'tests': [
    {'name': t['name'], 'source_sha256': t['production_sha256'], 'output': t['run']['stdout'].strip()}
    for t in record['tests']], 'source_checks': record['source_checks']}, ensure_ascii=False, indent=2))
