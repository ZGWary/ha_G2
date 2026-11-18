"""Add one bogus hoymiles_g2 registry entry to prove the reconcile path.

Usage: python inject_fake.py <core.entity_registry> <out.json> <unique_id> <entity_id> <domain>
"""
import json
import sys

src, dst, unique_id, entity_id, domain = sys.argv[1:6]

with open(src, "r", encoding="utf-8") as fh:
    data = json.load(fh)

entities = data["data"]["entities"]
if any(e.get("unique_id") == unique_id for e in entities):
    print("already present")
else:
    entries = list(entities.values()) if isinstance(entities, dict) else entities
    if entries:
        template = entries[0]
    else:
        template = {}
    entry = {
        "aliases": [],
        "area_id": None,
        "categories": {},
        "config_entry_id": None,
        "created_at": "2026-11-16T00:00:00.000000+00:00",
        "device_id": None,
        "disabled_by": None,
        "entity_category": None,
        "entity_id": entity_id,
        "hidden_by": None,
        "icon": None,
        "id": "f0f0f0f0f0f0f0f0f0f0f0f0f0f0f0f0",
        "labels": [],
        "modified_at": "2026-11-16T00:00:00.000000+00:00",
        "name": None,
        "object_id_base": entity_id.split(".", 1)[1],
        "options": None,
        "original_name": None,
        "platform": "hoymiles_g2",
        "previous_unique_id": None,
        "unique_id": unique_id,
    }
    if isinstance(entities, dict):
        entities[entry["id"]] = entry
    else:
        entities.append(entry)
    print("injected", unique_id)

with open(dst, "w", encoding="utf-8") as fh:
    json.dump(data, fh)
