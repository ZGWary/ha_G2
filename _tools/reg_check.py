"""Quick integrity check of a downloaded core.entity_registry."""
import json
import sys

path = sys.argv[1]
with open(path, "r", encoding="utf-8") as fh:
    data = json.load(fh)

entities = data["data"]["entities"]
values = list(entities.values()) if isinstance(entities, dict) else entities

print("total entries:", len(values))
print(
    "bogus present:",
    any(e.get("unique_id") == "hoymiles_g2_RMI-4161A0209FF6_tou_plan_status" for e in values),
)
print("f0f0 id present:", any(str(e.get("id", "")).startswith("f0f0") for e in values))

counts: dict[str, int] = {}
for entry in values:
    if entry.get("platform") != "hoymiles_g2":
        continue
    unique_id = entry.get("unique_id") or ""
    assert unique_id.startswith("hoymiles_g2_"), unique_id
    rest = unique_id[len("hoymiles_g2_"):]
    dev = rest.split("_", 1)[0]
    counts[dev] = counts.get(dev, 0) + 1

for dev in sorted(counts):
    print(f"  {dev}: {counts[dev]}")
