#!/usr/bin/env python3
"""Reuse verified existing load commands while replacing all tweak binaries."""

import os
from pathlib import Path

script = Path(os.environ["THEOS"]) / "mod/jailed/bin/ipa.sh"
original = script.read_text()
changes = {
    'install_name_tool -add_rpath "@executable_path/$COPY_PATH" "$app_binary"':
        'python3 "$GITHUB_WORKSPACE/source/Scripts/codex-verify-existing-load.py" "$app_binary" --rpath "@executable_path/$COPY_PATH" >> "$GITHUB_WORKSPACE/artifacts/injection-verification.log" 2>&1 || error "Expected main rpath missing"',
    '"$INSERT_DYLIB" --inplace --weak --no-strip-codesig "@rpath/$(basename "$file")" "$app_binary"':
        'python3 "$GITHUB_WORKSPACE/source/Scripts/codex-verify-existing-load.py" "$app_binary" --load "@rpath/$(basename "$file")" >> "$GITHUB_WORKSPACE/artifacts/injection-verification.log" 2>&1',
}
updated = original
for old, new in changes.items():
    assert updated.count(old) == 1, "Pinned Jailed command changed"
    updated = updated.replace(old, new)
script.with_suffix(".sh.original").write_text(original)
script.write_text(updated)
print("Jailed main executable is preserved; verify existing rpath and all tweak load commands")
