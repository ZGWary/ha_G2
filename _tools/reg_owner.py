"""Show which integration owns each entity of one device, from a registry copy.

Usage:  python reg_owner.py <registry.json> [SN_SUFFIX]
"""

from __future__ import annotations

import json
import sys

path = sys.argv[1]
sn = (sys.argv[2] if len(sys.argv) > 2 else "4161a0209ff6").lower()

with open(path, encoding="utf-8") as handle:
    data = json.load(handle)

rows = []
for entity in data["data"]["entities"]:
    blob = json.dumps(entity).lower()
    if sn in blob:
        rows.append(entity)

rows.sort(key=lambda e: (e.get("platform") or "", e.get("entity_id")))
print(f"entries mentioning {sn}: {len(rows)}\n")
for entity in rows:
    print(
        f"{entity.get('platform','?'):<14} "
        f"{entity.get('entity_id','?'):<52} "
        f"unique_id={entity.get('unique_id','?')}"
    )

print("\nby platform:")
counts: dict[str, int] = {}
for entity in rows:
    counts[entity.get("platform") or "?"] = counts.get(entity.get("platform") or "?", 0) + 1
for platform, count in sorted(counts.items()):
    print(f"  {platform}: {count}")
