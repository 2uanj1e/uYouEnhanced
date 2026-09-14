#!/usr/bin/env python3
"""Check an already present Mach-O dependency without editing the executable."""

import argparse
import subprocess

parser = argparse.ArgumentParser()
parser.add_argument("binary")
choice = parser.add_mutually_exclusive_group(required=True)
choice.add_argument("--rpath")
choice.add_argument("--load")
args = parser.parse_args()
flag = "-l" if args.rpath else "-L"
result = subprocess.run(["otool", flag, args.binary], text=True, capture_output=True)
assert result.returncode == 0, result.stderr
if args.rpath:
    found = any(line.strip().split(" (offset", 1)[0] == "path " + args.rpath
                for line in result.stdout.splitlines())
else:
    found = any(line.strip().split(" (compatibility version", 1)[0] == args.load
                for line in result.stdout.splitlines() if line.startswith("\t"))
assert found, f"Expected existing load/rpath missing: {args.rpath or args.load}"
print(f"PASS: preserved existing {args.rpath or args.load}")
