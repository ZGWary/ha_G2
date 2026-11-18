"""Report hoymiles_g2 entity-registry entries grouped by device id."""
import json
import os
import sys

path = sys.argv[1]
with open(path, encoding="utf-8") as fh:
    data = json.load(fh)

groups: dict[str, list[str]] = {}
for item in data.get("data", {}).get("entities", []):
    if item.get("platform") != "hoymiles_g2":
        continue
    uid = item.get("unique_id") or ""
    key = item.get("device_id") or "?"
    groups.setdefault(key, []).append(f"{item.get('entity_id')} => {uid}")

for key, rows in sorted(groups.items()):
    print(f"== {key}  ({len(rows)})")
    for row in sorted(rows):
        print("   " + row)
