#!/usr/bin/env python3
"""Use the rebuilt upstream optool for the pinned Jailed injection call."""

import os
from pathlib import Path

script = Path(os.environ["THEOS"]) / "mod/jailed/bin/ipa.sh"
original = script.read_text()
old = '"$INSERT_DYLIB" --inplace --weak --no-strip-codesig "@rpath/$(basename "$file")" "$app_binary"'
new = '"$OPTOOL" install -c weak -p "@rpath/$(basename "$file")" -t "$app_binary"'
assert original.count(old) == 1, "Pinned Jailed injection call changed"
script.with_suffix(".sh.original").write_text(original)
script.write_text(original.replace(old, new))
assert script.read_text().count(new) == 1
print("Jailed inject: rebuilt optool install -c weak; original call preserved in ipa.sh.original")
