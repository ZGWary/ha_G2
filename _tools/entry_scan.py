"""Summarise hoymiles_g2 config entries."""
import json
import sys

with open(sys.argv[1], encoding="utf-8") as fh:
    data = json.load(fh)

for entry in data.get("data", {}).get("entries", []):
    if entry.get("domain") != "hoymiles_g2":
        continue
    print(entry.get("title"), "|", entry.get("entry_id"), "|", entry.get("data"),
          "| disabled:", entry.get("disabled_by"))
