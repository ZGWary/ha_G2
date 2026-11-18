"""Print one captured payload per device topic family (read-only)."""

from __future__ import annotations

import json
from pathlib import Path

HERE = Path(__file__).parent
WANT = ("quick/state", "device/state", "system/state", "alarm/state")

seen: dict[str, str] = {}
for name in ("mqtt-FC22.jsonl", "mqtt-full.jsonl"):
    path = HERE / name
    if not path.exists():
        continue
    for line in path.read_text(encoding="utf-8").splitlines():
        try:
            obj = json.loads(line)
        except ValueError:
            continue
        topic = obj.get("topic", "")
        for suffix in WANT:
            if topic.endswith(suffix):
                key = topic.split("/")[-2] + "/" + suffix
                if key not in seen:
                    seen[key] = obj.get("payload", "")

for key in sorted(seen):
    payload = seen[key]
    try:
        fields = sorted(json.loads(payload))
    except ValueError:
        fields = ["<not json>"]
    print(f"\n=== {key} ({len(fields)} fields) ===")
    print(", ".join(fields)[:900])
