"""Show creation / modification timestamps of one device's entities."""

from __future__ import annotations

import json
import sys

path = sys.argv[1]
sn = (sys.argv[2] if len(sys.argv) > 2 else "4161a0209ff6").lower()

with open(path, encoding="utf-8") as handle:
    data = json.load(handle)

rows = [
    e
    for e in data["data"]["entities"]
    if sn in json.dumps(e).lower()
]
rows.sort(key=lambda e: (e.get("created_at") or "", e.get("entity_id")))

print(f"{'created_at':<28} {'modified_at':<28} {'platform':<11} entity_id")
for entity in rows:
    print(
        f"{str(entity.get('created_at')):<28} "
        f"{str(entity.get('modified_at')):<28} "
        f"{entity.get('platform','?'):<11} "
        f"{entity.get('entity_id','?')}"
    )
