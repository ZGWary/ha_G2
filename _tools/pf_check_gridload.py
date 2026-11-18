r"""Sanity-check the gridload entries inside PF_ICONS (no bulk read)."""
import io
import json
import os
import re
import struct
import base64

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
JS = os.path.join(ROOT, "_g2src", "hoymiles_g2", "www", "hoymiles-g2-power-flow.js")
SRC = os.path.join(HERE, "pf_gridload.json")

with io.open(JS, encoding="utf-8") as handle:
    source = handle.read()

with io.open(SRC, encoding="utf-8") as handle:
    want = json.load(handle)

for key in ("gridload.on", "gridload.off"):
    match = re.search(r'"%s":\s*"(data:image/png;base64,[^"]+)"' % re.escape(key), source)
    if not match:
        raise SystemExit("MISSING %s" % key)
    url = match.group(1)
    raw = base64.b64decode(url.split(",", 1)[1])
    width, height = struct.unpack(">II", raw[16:24])
    print("%-14s %d chars  %dx%d  matches_official=%s"
          % (key, len(url), width, height, url == want[key]))
