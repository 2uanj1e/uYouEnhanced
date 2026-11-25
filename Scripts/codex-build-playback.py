#!/usr/bin/env python3
"""Pinned paired build: retain current upstream features and verify local fixes.

All binary output stays local or in an explicitly private GitHub draft release.
No Apple/Google account input, device installation, or proxy changes occur here.
"""
import hashlib
import json
import os
from pathlib import Path, PurePosixPath
import plistlib
import posixpath
import re
import shutil
import stat
import subprocess
import sys
import time
import zipfile

ROOT = Path(os.environ.get("GITHUB_WORKSPACE", Path(__file__).resolve().parents[2])).resolve()
SOURCE = Path(os.environ.get("CODEX_SOURCE_ROOT", ROOT / "source")).resolve()
OUT = ROOT / "artifacts"
INPUT = ROOT / "input"
VERSION = "21.20.4"
UYOU_VERSION = "3.0.5"
SDK_VERSION = "26.5"
BUNDLE_ID = "com.google.ios.youtube"
PINNED_INPUT_SHA256 = "cdc908526c21acd083256b3cb8902db5841dcc5747337b9bea301894202a1d72"
PINNED_MAIN_SHA256 = "c8cfdf6aa8f6a6284b88f51699f66eaee8d014d38cb4abc702700739fac94815"
DEFAULT_INPUT_URL = "https://archive.org/download/YouTubeRebornPlus_19.10.5-4.2.6/yt-uYE-21204-305.ipa"
TWEAKS = {
    "uYouEnhanced.dylib", "uYou.dylib", "libFLEX.dylib", "YTABConfig.dylib",
    "YTIcons.dylib", "YouGroupSettings.dylib", "YouLoop.dylib", "YouMute.dylib",
    "YouPiP.dylib", "YouQuality.dylib", "YouSlider.dylib", "YouSpeed.dylib",
    "YouTimeStamp.dylib", "YouTubeDislikesReturn.dylib", "DontEatMyContent.dylib",
    "YTHoldForSpeed.dylib", "YTVideoOverlay.dylib", "YTweaks.dylib", "YouTubeLegacy.dylib",
}
OPTIONAL_TWEAKS = {"YTUHD.dylib", "iSponsorBlock.dylib"}
REPLACED_DEPENDENCIES = {"Alderis.framework", "CydiaSubstrate.framework", "libcolorpicker.dylib"}
FFMPEG = ("ffmpegkit", "libavcodec", "libavdevice", "libavfilter", "libavformat",
          "libavutil", "libswresample", "libswscale")
RECORD = {"commands": [], "variants": {}, "source_commit": os.environ.get("GITHUB_SHA"),
          "base_version": VERSION, "sdk_version": SDK_VERSION,
          "device_acceptance": "pending actual iPhone playback/sign-in/refresh testing"}
if (OUT / "verification.json").exists():
    RECORD = json.loads((OUT / "verification.json").read_text())


def digest(path):
    h = hashlib.sha256()
    with Path(path).open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            h.update(block)
    return h.hexdigest()


def save_record():
    OUT.mkdir(parents=True, exist_ok=True)
    (OUT / "verification.json").write_text(json.dumps(RECORD, indent=2) + "\n")


def run(args, *, cwd=None, log=None, redact=False):
    argv = [str(x) for x in args]
    started = time.monotonic()
    print(f"Starting {Path(argv[0]).name}" + (f" ({log})" if log else ""), flush=True)
    result = subprocess.run(argv, cwd=cwd, text=True, stdout=subprocess.PIPE,
                            stderr=subprocess.STDOUT, check=False)
    command = [argv[0], "<verified-input-url>"] if redact else argv
    output = result.stdout
    if redact:
        for value in (os.environ.get("YOUTUBE_URL", ""), os.environ.get("GH_TOKEN", "")):
            if value:
                output = output.replace(value, "<redacted>")
    item = {"command": command, "cwd": str(cwd or ROOT), "exit_status": result.returncode,
            "elapsed_seconds": round(time.monotonic() - started, 3)}
    if log:
        (OUT / log).write_text(output)
        item["literal_output_file"] = log
    else:
        item["literal_output"] = output
    RECORD["commands"].append(item)
    save_record()
    print(f"Finished {Path(argv[0]).name}: exit {result.returncode}, {item['elapsed_seconds']}s", flush=True)
    if result.returncode:
        print("\n".join(output.splitlines()[-100:]), file=sys.stderr)
        raise RuntimeError(f"Command failed: {command[0]} (exit {result.returncode})")
    return output


def archive_inventory(ipa):
    """Validate ZIP members before extraction, including symlink containment."""
    with zipfile.ZipFile(ipa) as archive:
        assert archive.testzip() is None, "ZIP CRC failure"
        for item in archive.infolist():
            path = PurePosixPath(item.filename)
            assert not path.is_absolute() and ".." not in path.parts, item.filename
            if stat.S_ISLNK(item.external_attr >> 16):
                link = archive.read(item).decode("utf-8")
                resolved = posixpath.normpath(posixpath.join(str(path.parent), link))
                assert not link.startswith("/") and resolved != ".." and not resolved.startswith("../"), item.filename
        return archive.namelist()


def unpack(ipa, destination):
    archive_inventory(ipa)
    assert not destination.exists(), f"Extraction target already exists: {destination}"
    run(["ditto", "-x", "-k", ipa, destination])
    apps = list((destination / "Payload").glob("*.app"))
    assert len(apps) == 1, "Expected one primary application"
    return apps[0]


def dependencies(binary):
    lines = run(["otool", "-L", binary]).splitlines()[1:]
    return [line.strip().split(" (compatibility version", 1)[0] for line in lines
            if line.startswith("\t")]


def file_manifest(root):
    result = {}
    for path in sorted(root.rglob("*")):
        relative = str(path.relative_to(root))
        if path.is_symlink():
            result[relative] = {"symlink": os.readlink(path)}
        elif path.is_file():
            result[relative] = {"bytes": path.stat().st_size, "sha256": digest(path)}
    return result


def reuse_ffmpeg(app):
    media = app / "uYouMedia.bundle"
    module_root = SOURCE / "modules/ffmpeg"
    binary_hashes = {}
    trees = {}
    for name in FFMPEG:
        original = media / f"{name}.framework"
        assert (original / name).is_file(), f"Missing required FFmpeg input framework: {name}"
        before = file_manifest(original)
        target = module_root / original.name
        if target.exists():
            assert file_manifest(target) == before, f"Existing FFmpeg modules differ: {name}"
        else:
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copytree(original, target, symlinks=True)
        assert file_manifest(target) == before
        binary_hashes[name] = digest(target / name)
        trees[name] = before
    assert len(binary_hashes) == 8
    RECORD["ffmpeg_reuse"] = {
        "source": "pinned input IPA / Payload/YouTube.app/uYouMedia.bundle",
        "staged_source": "source/modules/ffmpeg", "framework_count": 8,
        "binary_sha256_before_resign": binary_hashes, "framework_file_manifests": trees,
        "all_input_framework_trees_retained": True,
        "fresh_ffmpeg_source_build": False,
    }
    save_record()


def clean_old_injection(app):
    info = plistlib.loads((app / "Info.plist").read_bytes())
    assert info["CFBundleIdentifier"] == BUNDLE_ID
    assert info["CFBundleShortVersionString"] == VERSION
    binary = app / info["CFBundleExecutable"]
    raw_sha = digest(binary)
    assert raw_sha == PINNED_MAIN_SHA256, "Unexpected input main executable"
    before = dependencies(binary)
    actual_tweaks = [x.removeprefix("@rpath/") for x in before
                     if x.startswith("@rpath/") and x.removeprefix("@rpath/") in TWEAKS | OPTIONAL_TWEAKS]
    assert len(actual_tweaks) == 21 and set(actual_tweaks) == TWEAKS | OPTIONAL_TWEAKS, actual_tweaks
    normalization = OUT / "input-load-normalization.json"
    run(["python3", SOURCE / "Scripts/codex-prepare-loads.py", binary, "--record", normalization])
    normalized_sha = digest(binary)
    normalized = json.loads(normalization.read_text())
    assert normalized["before_sha256"] == raw_sha and normalized["after_sha256"] == normalized_sha
    after = dependencies(binary)
    assert after == [d for d in before if d not in {"@rpath/" + n for n in OPTIONAL_TWEAKS}]
    retained = [x.removeprefix("@rpath/") for x in after
                if x.startswith("@rpath/") and x.removeprefix("@rpath/") in TWEAKS]
    assert len(retained) == 19 and set(retained) == TWEAKS
    widevine = app / "Frameworks/widevine_cdm_secured_ios.framework/widevine_cdm_secured_ios"
    widevine_before = digest(widevine)
    reuse_ffmpeg(app)
    removed_files = []
    for name in sorted(TWEAKS | OPTIONAL_TWEAKS | REPLACED_DEPENDENCIES):
        path = app / "Frameworks" / name
        if path.is_dir():
            shutil.rmtree(path)
            removed_files.append("Frameworks/" + name)
        elif path.exists():
            path.unlink()
            removed_files.append("Frameworks/" + name)
    # Rebuild only known tweak resource bundles, not Google's resource bundles.
    for source_bundle in sorted((SOURCE / "Bundles").glob("*.bundle")):
        path = app / source_bundle.name
        if path.is_dir():
            shutil.rmtree(path)
            removed_files.append(source_bundle.name)
        elif path.is_symlink():
            path.unlink()
            removed_files.append(source_bundle.name)
    assert dependencies(binary) == after and digest(binary) == normalized_sha
    assert digest(widevine) == widevine_before
    RECORD["input_cleanup"] = {
        "raw_main_sha256": raw_sha, "main_sha256": normalized_sha,
        "normalization": normalized, "removed_tweak_files_and_resources": removed_files,
        "preserved_load_commands": ["@rpath/" + n for n in retained],
        "remaining_load_commands": after, "google_widevine_sha256": widevine_before,
        "google_widevine_unchanged": True, "main_unchanged_after_bounded_normalization": True,
    }
    save_record()


def check_ffmpeg_before_resign(app):
    actual = {}
    for name in FFMPEG:
        binary = app / "uYouMedia.bundle" / f"{name}.framework" / name
        assert binary.is_file(), f"Incomplete FFmpeg output: {name}"
        actual[name] = digest(binary)
    assert actual == RECORD["ffmpeg_reuse"]["binary_sha256_before_resign"], "FFmpeg binaries changed before final re-signing"
    return actual


def verify_app(app):
    info = plistlib.loads((app / "Info.plist").read_bytes())
    assert info["CFBundleIdentifier"] == BUNDLE_ID
    assert info["CFBundleShortVersionString"] == VERSION and info["CFBundleVersion"] == VERSION
    assert info.get("MinimumOSVersion") == "16.0", info.get("MinimumOSVersion")
    binary = app / info["CFBundleExecutable"]
    assert "arm64" in run(["lipo", "-archs", binary]).split()
    commands = run(["otool", "-l", binary])
    cryptids = re.findall(r"^\s*cryptid\s+(\d+)\s*$", commands, re.MULTILINE)
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
            if relative in TWEAKS:
                injected.append(relative)
            assert relative not in OPTIONAL_TWEAKS, f"Unexpected optional tweak load: {relative}"
        elif name.startswith("@executable_path/"):
            assert (app / name.removeprefix("@executable_path/")).is_file(), name
    assert len(injected) == len(TWEAKS) and set(injected) == TWEAKS, injected
    assert len(injected) == len(set(injected)), "Duplicate tweak loads"
    for optional in OPTIONAL_TWEAKS:
        assert not (app / "Frameworks" / optional).exists(), optional
    extensions = []
    for path in app.rglob("*.appex"):
        assert path.parent == app / "PlugIns", f"Unresignable extension path: {path}"
        ext = plistlib.loads((path / "Info.plist").read_bytes())
        assert ext["CFBundleIdentifier"].startswith(BUNDLE_ID + "."), ext["CFBundleIdentifier"]
        extensions.append({"path": str(path.relative_to(app)), "bundle_id": ext["CFBundleIdentifier"]})
    assert not (app / "Watch").exists() and not (app / "AppClips").exists()
    for name in FFMPEG:
        assert (app / "uYouMedia.bundle" / f"{name}.framework" / name).is_file()
    run(["codesign", "--verify", "--deep", "--strict", "--verbose=2", app])
    return {"version": info["CFBundleShortVersionString"], "bundle_id": info["CFBundleIdentifier"],
            "minimum_ios": info["MinimumOSVersion"], "cryptids": cryptids,
            "parsed_plists": plist_count, "injected_tweaks": sorted(injected),
            "extensions": extensions, "ffmpeg_framework_count": 8}


def build_variant(label, enabled, clean_app):
    build = ROOT / "builds/shared"
    if not build.exists():
        shutil.copytree(SOURCE, build, symlinks=True,
                        ignore=shutil.ignore_patterns(".git", ".theos", "packages", "__pycache__"))
    app = build / "Payload/YouTube.app"
    if not app.exists():
        app.parent.mkdir(exist_ok=True)
        shutil.copytree(clean_app, app, symlinks=True)
    if enabled:
        assert "baseline" in RECORD["variants"], "Incremental build requires verified baseline"
        obj = build / ".theos/obj"
        for path in list(obj.rglob("Sources")):
            if path.is_dir():
                shutil.rmtree(path)
        for path in list(obj.rglob("uYouEnhanced.dylib")):
            path.unlink()
    args = ["make", "package", "THEOS_PACKAGE_SCHEME=rootless", "IPA=Payload/YouTube.app",
            "FINALPACKAGE=1", f"SDK_VERSION={SDK_VERSION}", "UYOU_VERSION=3.0.4",
            f"YOUTUBE_VERSION={VERSION}", f"CODEX_PLAYBACK_FIXES={enabled}",
            f"PACKAGE_VERSION={VERSION}-{UYOU_VERSION}-{label}",
            f"BUNDLE_ID={BUNDLE_ID}", "DISPLAY_NAME=YouTube", "YTUHD_ENABLED=0", "SPONSORBLOCK_ENABLED=0"]
    if enabled:
        args.append("SUBPROJECTS=")
    previous_packages = set((build / "packages").glob("*.ipa"))
    run(args, cwd=build, log=f"{label}-build.log")
    packages = list(set((build / "packages").glob("*.ipa")) - previous_packages)
    assert len(packages) == 1, packages
    stage = ROOT / "signed" / label
    stage.parent.mkdir(parents=True, exist_ok=True)
    signed_app = unpack(packages[0], stage)
    info = plistlib.loads((signed_app / "Info.plist").read_bytes())
    assert digest(signed_app / info["CFBundleExecutable"]) == RECORD["input_cleanup"]["main_sha256"], "Packaging changed normalized main executable"
    ffmpeg_hashes = check_ffmpeg_before_resign(signed_app)
    widevine = signed_app / "Frameworks/widevine_cdm_secured_ios.framework/widevine_cdm_secured_ios"
    assert digest(widevine) == RECORD["input_cleanup"]["google_widevine_sha256"], "Packaging changed Google's Widevine component"
    # These are unsigned/ad-hoc personal-build artifacts, not installed profiles.
    for profile in signed_app.rglob("embedded.mobileprovision"):
        profile.unlink()
    for sc_info in list(signed_app.rglob("SC_Info")):
        if sc_info.is_dir():
            shutil.rmtree(sc_info)
    run(["codesign", "--force", "--deep", "--sign", "-", "--timestamp=none",
         "--preserve-metadata=identifier,entitlements", signed_app])
    result = verify_app(signed_app)
    target = OUT / f"uYouEnhanced_{VERSION}_{UYOU_VERSION}_{label}-no-spoof.ipa"
    assert not target.exists(), target
    run(["zip", "-q", "-r", "-y", target, "Payload"], cwd=stage)
    archive_inventory(target)
    result.update({"artifact": target.name, "sha256": digest(target), "bytes": target.stat().st_size,
                   "CODEX_PLAYBACK_FIXES": enabled, "main_unchanged_after_normalization_before_resign": True,
                   "ffmpeg_sha256_before_resign": ffmpeg_hashes, "ffmpeg_source_binaries_preserved": True,
                   "device_playback_and_signin_test": "pending user device test"})
    RECORD["variants"][label] = result
    save_record()
    print(f"Built and statically verified {target.name}: {result['sha256']}", flush=True)


def prepare_input():
    OUT.mkdir(parents=True, exist_ok=True)
    INPUT.mkdir(parents=True, exist_ok=True)
    ipa = INPUT / "upstream.ipa"
    declared_sha = os.environ.get("YOUTUBE_SHA256", PINNED_INPUT_SHA256).strip().lower()
    assert declared_sha == PINNED_INPUT_SHA256, "This recipe is pinned to the audited 21.20.4 input"
    input_tag = os.environ.get("INPUT_TAG", "").strip()
    local = os.environ.get("LOCAL_INPUT_PATH", "").strip()
    if local:
        path = Path(local).resolve()
        assert digest(path) == PINNED_INPUT_SHA256
        if path != ipa.resolve():
            if ipa.exists():
                assert digest(ipa) == PINNED_INPUT_SHA256
            else:
                shutil.copy2(path, ipa)
        RECORD["input_mode"] = "existing local verified file"
    elif input_tag:
        meta = json.loads(run(["gh", "release", "view", input_tag, "--repo", os.environ["GITHUB_REPOSITORY"],
                               "--json", "isDraft,tagName"]))
        assert meta["isDraft"] is True, "Input release must remain a private draft"
        run(["gh", "release", "download", input_tag, "--repo", os.environ["GITHUB_REPOSITORY"],
             "--pattern", "yt-uYE-21204-305.ipa", "--dir", INPUT])
        candidates = list(INPUT.glob("*.ipa"))
        assert len(candidates) == 1, "Expected exactly one temporary draft input asset"
        if candidates[0] != ipa:
            assert not ipa.exists()
            candidates[0].rename(ipa)
        RECORD["input_mode"] = "temporary private draft release"
        RECORD["input_release_tag"] = input_tag
    else:
        url = os.environ.get("YOUTUBE_URL", DEFAULT_INPUT_URL).strip()
        assert url.startswith("https://"), "Input URL must use HTTPS"
        run(["curl", "--fail", "--location", "--connect-timeout", "30", "--max-time", "360",
             "--silent", "--show-error", url, "--output", ipa], redact=True)
        RECORD["input_mode"] = "maintainer-referenced verified HTTPS input"
    actual = digest(ipa)
    assert actual == PINNED_INPUT_SHA256, "Input SHA-256 mismatch"
    RECORD["input_sha256"] = actual
    RECORD["input_bytes"] = ipa.stat().st_size
    run(["git", "submodule", "status", "--recursive"], cwd=SOURCE, log="submodule-commits.txt")
    app = unpack(ipa, INPUT / "extracted")
    clean_old_injection(app)


def main():
    phase = sys.argv[1] if len(sys.argv) > 1 else "all"
    assert phase in {"prepare", "baseline", "modified", "all"}, phase
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
