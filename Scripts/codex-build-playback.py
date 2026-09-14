#!/usr/bin/env python3
"""One-run CI orchestration for a paired playback regression build."""

import hashlib
import json
import os
from pathlib import Path, PurePosixPath
import plistlib
import re
import shutil
import subprocess
import sys
import time
import zipfile


ROOT = Path(os.environ["GITHUB_WORKSPACE"])
OUT = ROOT / "artifacts"
SOURCE = ROOT / "source"
INPUT = ROOT / "input"
RECORD = {"commands": [], "variants": {}, "source_commit": os.environ.get("GITHUB_SHA")}
if (OUT / "verification.json").exists():
    RECORD = json.loads((OUT / "verification.json").read_text())
OLD_DYLIBS = {
    "uYouEnhanced.dylib", "uYou.dylib", "libFLEX.dylib", "YTABConfig.dylib",
    "YTIcons.dylib", "YouGroupSettings.dylib", "YouLoop.dylib", "YouMute.dylib",
    "YouPiP.dylib", "YouQuality.dylib", "YouSlider.dylib", "YouSpeed.dylib",
    "YouTimeStamp.dylib", "YouTubeDislikesReturn.dylib", "DontEatMyContent.dylib",
    "YTHoldForSpeed.dylib", "YTVideoOverlay.dylib", "YTweaks.dylib",
}
OLD_DEPENDENCIES = {"Alderis.framework", "CydiaSubstrate.framework", "libcolorpicker.dylib"}


def digest(path):
    h = hashlib.sha256()
    with Path(path).open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            h.update(block)
    return h.hexdigest()


def save_record():
    OUT.mkdir(exist_ok=True)
    (OUT / "verification.json").write_text(json.dumps(RECORD, indent=2) + "\n")


def run(args, *, cwd=None, log=None, redact=False):
    argv = [str(x) for x in args]
    started = time.monotonic()
    print(f"Starting {Path(argv[0]).name}" + (f" ({log})" if log else ""), flush=True)
    result = subprocess.run(argv, cwd=cwd, text=True, stdout=subprocess.PIPE,
                            stderr=subprocess.STDOUT, check=False)
    command = ["curl", "<verified-input-url>"] if redact else argv
    item = {"command": command, "cwd": str(cwd or ROOT), "exit_status": result.returncode}
    item["elapsed_seconds"] = round(time.monotonic() - started, 3)
    if log:
        (OUT / log).write_text(result.stdout)
        item["literal_output_file"] = log
    else:
        item["literal_output"] = result.stdout
    RECORD["commands"].append(item)
    save_record()
    print(f"Finished {Path(argv[0]).name}: exit {result.returncode}, {item['elapsed_seconds']}s", flush=True)
    if result.returncode:
        print("\n".join(result.stdout.splitlines()[-100:]), file=sys.stderr)
        raise RuntimeError(f"Command failed: {command[0]} (exit {result.returncode})")
    return result.stdout


def unpack(ipa, destination):
    with zipfile.ZipFile(ipa) as archive:
        assert archive.testzip() is None, "ZIP CRC failure"
        for item in archive.infolist():
            path = PurePosixPath(item.filename)
            assert not path.is_absolute() and ".." not in path.parts, item.filename
    run(["ditto", "-x", "-k", ipa, destination])
    apps = list((destination / "Payload").glob("*.app"))
    assert len(apps) == 1, "Expected one primary application"
    return apps[0]


def dependencies(binary):
    lines = run(["otool", "-L", binary]).splitlines()[1:]
    return [line.strip().split(" (compatibility version", 1)[0] for line in lines
            if line.startswith("\t")]


def clean_old_injection(app):
    info = plistlib.loads((app / "Info.plist").read_bytes())
    assert info["CFBundleIdentifier"] == "com.google.ios.youtube"
    assert info["CFBundleShortVersionString"] == "21.14.4"
    binary = app / info["CFBundleExecutable"]
    before = dependencies(binary)
    removed = [name for name in before if name.startswith("@rpath/")
               and name.removeprefix("@rpath/") in OLD_DYLIBS]
    assert len(removed) == 18, f"Input injection count changed: {removed}"
    widevine = app / "Frameworks/widevine_cdm_secured_ios.framework/widevine_cdm_secured_ios"
    widevine_before = digest(widevine)
    for name in removed:
        run([os.environ["OPTOOL"], "uninstall", "-p", name, "-t", binary])
    removed_files = []
    for name in sorted(OLD_DYLIBS | OLD_DEPENDENCIES):
        path = app / "Frameworks" / name
        if path.is_dir():
            shutil.rmtree(path)
            removed_files.append(name)
        elif path.exists():
            path.unlink()
            removed_files.append(name)
    after = dependencies(binary)
    assert after == [name for name in before if name not in removed]
    assert digest(widevine) == widevine_before
    RECORD["input_cleanup"] = {
        "removed_load_commands": removed, "removed_tweak_files": removed_files,
        "remaining_load_commands": after, "google_widevine_sha256": widevine_before,
        "google_widevine_unchanged": True,
    }
    save_record()


def verify_app(app):
    info = plistlib.loads((app / "Info.plist").read_bytes())
    assert info["CFBundleIdentifier"] == "com.google.ios.youtube"
    binary = app / info["CFBundleExecutable"]
    assert "arm64" in run(["lipo", "-archs", binary]).split()
    load_commands = run(["otool", "-l", binary])
    cryptids = re.findall(r"^\s*cryptid\s+(\d+)\s*$", load_commands, re.MULTILINE)
    assert cryptids and all(value == "0" for value in cryptids), cryptids
    plist_count = 0
    for path in app.rglob("*.plist"):
        if path.is_file():
            plistlib.loads(path.read_bytes())
            plist_count += 1
    injected = []
    for name in dependencies(binary):
        if name.startswith("@rpath/"):
            relative = name.removeprefix("@rpath/")
            assert (app / "Frameworks" / relative).is_file(), f"Missing dependency: {name}"
            if relative in OLD_DYLIBS:
                injected.append(relative)
    assert set(injected) == OLD_DYLIBS, injected
    assert len(injected) == len(set(injected)), "Duplicate tweak loads"
    run(["codesign", "--verify", "--deep", "--strict", "--verbose=2", app])
    return {"version": info["CFBundleShortVersionString"],
            "bundle_id": info["CFBundleIdentifier"], "cryptids": cryptids,
            "parsed_plists": plist_count, "injected_tweaks": sorted(injected)}


def build_variant(label, enabled, clean_app):
    build = ROOT / "builds" / "shared"
    if not build.exists():
        shutil.copytree(SOURCE, build, symlinks=True,
                        ignore=shutil.ignore_patterns(".git", ".theos", "packages", "__pycache__"))
    app = build / "Payload/YouTube.app"
    if not app.exists():
        app.parent.mkdir(exist_ok=True)
        shutil.copytree(clean_app, app, symlinks=True)
    if enabled:
        assert "baseline" in RECORD["variants"], "Incremental build requires verified baseline"
        # Keep all subproject products. Rebuild the main tweak with the two
        # additional hooks and changed compiler definition.
        obj = build / ".theos/obj"
        for path in list(obj.rglob("Sources")):
            if path.is_dir():
                shutil.rmtree(path)
        for path in list(obj.rglob("uYouEnhanced.dylib")):
            path.unlink()
    args = ["make", "package", "THEOS_PACKAGE_SCHEME=rootless", "IPA=Payload/YouTube.app",
            "FINALPACKAGE=1", "SDK_VERSION=18.6", "UYOU_VERSION=3.0.4",
            "YOUTUBE_VERSION=21.14.4", f"CODEX_PLAYBACK_FIXES={enabled}",
            f"PACKAGE_VERSION=21.14.4-3.0.5-{label}",
            "BUNDLE_ID=com.google.ios.youtube", "DISPLAY_NAME=YouTube",
            "YTUHD_ENABLED=0", "SPONSORBLOCK_ENABLED=0"]
    if enabled:
        args.append("SUBPROJECTS=")
    previous_packages = set((build / "packages").glob("*.ipa"))
    run(args, cwd=build, log=f"{label}-build.log")
    packages = list(set((build / "packages").glob("*.ipa")) - previous_packages)
    assert len(packages) == 1, packages
    stage = ROOT / "signed" / label
    stage.mkdir(parents=True)
    signed_app = unpack(packages[0], stage)
    run(["codesign", "--force", "--deep", "--sign", "-", "--timestamp=none",
         "--preserve-metadata=identifier,entitlements", signed_app])
    result = verify_app(signed_app)
    target = OUT / f"uYouEnhanced_21.14.4_3.0.5_{label}-no-spoof.ipa"
    run(["zip", "-q", "-r", "-y", target, "Payload"], cwd=stage)
    with zipfile.ZipFile(target) as archive:
        assert archive.testzip() is None
        plistlib.loads(archive.read("Payload/YouTube.app/Info.plist"))
    result.update({"artifact": target.name, "sha256": digest(target),
                   "bytes": target.stat().st_size, "CODEX_PLAYBACK_FIXES": enabled,
                   "device_playback_and_signin_test": "pending user device test"})
    RECORD["variants"][label] = result
    save_record()
    print(f"Built and statically verified {target.name}: {result['sha256']}", flush=True)


def prepare_input():
    OUT.mkdir(exist_ok=True)
    INPUT.mkdir(exist_ok=True)
    ipa = INPUT / "upstream.ipa"
    input_tag = os.environ.get("INPUT_TAG", "").strip()
    if input_tag:
        run(["gh", "release", "download", input_tag, "--repo", os.environ["GITHUB_REPOSITORY"],
             "--pattern", "*.ipa", "--dir", INPUT, "--clobber"])
        candidates = list(INPUT.glob("*.ipa"))
        assert len(candidates) == 1, "Expected one temporary input asset"
        if candidates[0] != ipa:
            candidates[0].rename(ipa)
        RECORD["input_mode"] = "temporary draft release"
    urls = [os.environ["YOUTUBE_URL"],
            "https://ia600409.us.archive.org/24/items/YouTubeRebornPlus_19.10.5-4.2.6/yt-uYE-21144-305.ipa"]
    for url in ([] if input_tag else dict.fromkeys(urls)):
        try:
            run(["curl", "--fail", "--location", "--connect-timeout", "30",
                 "--max-time", "240", "--silent", "--show-error", "--continue-at", "-",
                 url, "--output", ipa], redact=True)
        except RuntimeError:
            print("Input endpoint did not finish; trying the verified mirror", flush=True)
        if ipa.exists() and digest(ipa) == os.environ["YOUTUBE_SHA256"].strip().lower():
            break
    actual = digest(ipa)
    assert actual == os.environ["YOUTUBE_SHA256"].strip().lower(), "Input SHA-256 mismatch"
    RECORD["input_sha256"] = actual
    RECORD["input_bytes"] = ipa.stat().st_size
    run(["git", "submodule", "status", "--recursive"], cwd=SOURCE, log="submodule-commits.txt")
    app = unpack(ipa, INPUT / "extracted")
    clean_old_injection(app)


def main():
    phase = sys.argv[1] if len(sys.argv) > 1 else "all"
    started = time.monotonic()
    print(f"Build phase: {phase}", flush=True)
    if phase in ("prepare", "all"):
        prepare_input()
    if phase in ("baseline", "all"):
        build_variant("baseline", 0, INPUT / "extracted/Payload/YouTube.app")
    if phase in ("modified", "all"):
        build_variant("playback-fix", 1, INPUT / "extracted/Payload/YouTube.app")
    lines = [f"{item['sha256']}  {item['artifact']}" for item in RECORD["variants"].values()]
    (OUT / "SHA256SUMS.txt").write_text("\n".join(lines) + "\n")
    print(f"Completed phase {phase} in {time.monotonic() - started:.1f}s", flush=True)


if __name__ == "__main__":
    try:
        main()
    finally:
        save_record()
