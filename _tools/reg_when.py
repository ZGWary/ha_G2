"""Show created/modified timestamps of registry entries for one serial."""

from __future__ import annotations

import json
import sys
from datetime import datetime

path = sys.argv[1]
want = (sys.argv[2] if len(sys.argv) > 2 else "4161a0209ff6").lower()

with open(path, encoding="utf-8") as handle:
    data = json.load(handle)

entities = data.get("data", {}).get("entities") or []
if isinstance(entities, dict):
    entities = list(entities.values())

rows = []
for entry in entities:
    entity_id = entry.get("entity_id") or ""
    if want not in entity_id.lower():
        continue
    rows.append(
        (
            entity_id,
            entry.get("platform"),
            entry.get("unique_id"),
            entry.get("created_at"),
            entry.get("modified_at"),
        )
    )

rows.sort(key=lambda row: (row[1] or "", row[0]))


def fmt(value: str | None) -> str:
    if not value:
        return "-"
    try:
        stamp = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return value[:19]
    return stamp.astimezone().strftime("%m-%d %H:%M:%S")


print(f"{'entity':<48} {'platform':<13} {'created':<15} {'modified':<15} uid")
for entity_id, platform, unique_id, created, modified in rows:
    print(
        f"{entity_id:<48} {str(platform):<13} {fmt(created):<15} "
        f"{fmt(modified):<15} {unique_id}"
    )
