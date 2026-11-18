r"""Bump the integration version in manifest.json (WSL/Windows safe, no BOM)."""
import io
import json
import os
import re
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
MANIFEST = os.path.join(os.path.dirname(HERE), "_g2src", "hoymiles_g2", "manifest.json")

new = sys.argv[1] if len(sys.argv) > 1 else "0.6.4"

with io.open(MANIFEST, encoding="utf-8") as handle:
    source = handle.read()

source, count = re.subn(r'("version"\s*:\s*")[^"]*(")',
                        lambda m: m.group(1) + new + m.group(2),
                        source, count=1)
if not count:
    raise SystemExit("no version key found")

with io.open(MANIFEST, "w", encoding="utf-8", newline="\n") as handle:
    handle.write(source)

with io.open(MANIFEST, encoding="utf-8") as handle:
    data = json.load(handle)

print("manifest.json -> %s / %s" % (data["domain"], data["version"]))
