"""Show the MQTT devices behind a serial, and which entities belong to them."""

from __future__ import annotations

import json
import sys

path = sys.argv[1]
sn = (sys.argv[2] if len(sys.argv) > 2 else "4161a0209ff6").lower()

with open(path, encoding="utf-8") as handle:
    data = json.load(handle)

entities = data["data"]["entities"]

print("=== devices whose identifiers mention the serial ===")
for device in data["data"]["devices"]:
    blob = json.dumps(device).lower()
    if sn not in blob:
        continue
    print(f"  id={device.get('id')}")
    print(f"    name={device.get('name')!r} model={device.get('model')!r}")
    print(f"    identifiers={device.get('identifiers')}")
    print(f"    via_device_id={device.get('via_device_id')}")
    print()

print("=== entity counts per device_id ===")
counts: dict[str, int] = {}
for entity in entities:
    if sn not in json.dumps(entity).lower():
        continue
    key = str(entity.get("device_id"))
    counts[key] = counts.get(key, 0) + 1
for device_id, count in sorted(counts.items(), key=lambda kv: -kv[1]):
    print(f"  {device_id}: {count}")

print("\n=== orphaned / disabled entities ===")
for entity in entities:
    if sn not in json.dumps(entity).lower():
        continue
    if entity.get("device_id") is None or entity.get("disabled_by"):
        print(
            f"  {entity.get('entity_id')} device_id={entity.get('device_id')} "
            f"disabled_by={entity.get('disabled_by')}"
        )
