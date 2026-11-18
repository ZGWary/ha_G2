"""Copy the `gridload.*` icons out of the official card into a JSON file.

The official integration ships the very same vendor icon set, and its
「电网&负载」 glyph is the one the G3 dashboard shows.  Rather than re-baking
the artwork, lift the two data-URLs verbatim.
"""

import io
import json
import os
import re
import sys

SRC = sys.argv[1] if len(sys.argv) > 1 else os.path.join(
    os.environ.get("TEMP", "."), "off-pf.js"
)
OUT = sys.argv[2] if len(sys.argv) > 2 else os.path.join(os.path.dirname(__file__), "pf_gridload.json")

with io.open(SRC, encoding="utf-8") as fh:
    text = fh.read()

found = {}
for key in ("gridload.on", "gridload.off"):
    m = re.search(r'"%s":\s*"(data:image/[^"]+)"' % re.escape(key), text)
    if not m:
        raise SystemExit("missing %s" % key)
    found[key] = m.group(1)

with io.open(OUT, "w", encoding="utf-8", newline="\n") as fh:
    json.dump(found, fh, ensure_ascii=False, indent=1)
    fh.write("\n")

for key, value in found.items():
    print(key, len(value))
print("written", OUT)
