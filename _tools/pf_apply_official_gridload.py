r"""Put the official 「电网&负载」 artwork into PF_ICONS.

    python _tools\pf_extract_gridload.py   # lift the two data URIs from the
                                           # official card into pf_gridload.json
    python _tools\pf_apply_official_gridload.py

Why copy instead of re-baking: the official integration ships the same vendor
icon set, and its `gridload` glyph (blue ring, house + pylon) is exactly what
the G3 dashboard shows.  Reusing those two 96x96 blobs keeps the two cards
pixel-identical and avoids another round of hand-built artwork.

Safe to re-run: an existing `gridload.*` pair is replaced, never duplicated.
"""
import io
import json
import os
import re

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
JS = os.path.join(ROOT, "_g2src", "hoymiles_g2", "www", "hoymiles-g2-power-flow.js")
SRC = os.path.join(HERE, "pf_gridload.json")


def main():
    with io.open(SRC, encoding="utf-8") as handle:
        icons = json.load(handle)

    for key in ("gridload.on", "gridload.off"):
        if key not in icons:
            raise SystemExit("missing %s in %s" % (key, SRC))
        if not icons[key].startswith("data:image/png;base64,iVBORw0KGgo"):
            raise SystemExit("%s is not a PNG data URI" % key)

    lines = ['    "%s": "%s",' % (key, icons[key])
             for key in ("gridload.on", "gridload.off")]
    block = "\n".join(lines)

    with io.open(JS, encoding="utf-8") as handle:
        source = handle.read()

    existing = re.search(r'^ *"gridload\.on": .*\n *"gridload\.off": .*$',
                         source, re.MULTILINE)
    if existing:
        source = source[:existing.start()] + block + source[existing.end():]
        action = "replaced"
    else:
        anchor = re.search(r'^ *"load\.off": .*$', source, re.MULTILINE)
        if not anchor:
            raise SystemExit('could not find the "load.off" line')
        cut = anchor.end()
        source = source[:cut] + "\n" + block + source[cut:]
        action = "inserted"

    with io.open(JS, "w", encoding="utf-8", newline="\n") as handle:
        handle.write(source)

    print("%s official gridload.on/off in %s"
          % (action, os.path.relpath(JS, ROOT)))
    print("file is now %d bytes" % len(source.encode("utf-8")))


if __name__ == "__main__":
    main()
