"""Group entity-registry entries by platform for the Hoymiles device ids."""
import json
import sys
from collections import defaultdict

with open(sys.argv[1], encoding="utf-8") as fh:
    data = json.load(fh)

DEVS = ("4161A0209FF6", "1650A028FC22", "4162A02ABFB5", "280024210095")

buckets = defaultdict(list)
for item in data.get("data", {}).get("entities", []):
    eid = item.get("entity_id") or ""
    for dev in DEVS:
        if dev.lower().replace("-", "") in eid.replace("-", "").lower() or \
                dev.lower() in (item.get("unique_id") or "").lower():
            buckets[(dev, item.get("platform"))].append(eid)
            break

for (dev, plat), rows in sorted(buckets.items()):
    print(f"== {dev}  [{plat}]  ({len(rows)})")
    for row in sorted(rows):
        print("   " + row)
