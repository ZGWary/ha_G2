"""Compare, per serial: inventory keys vs retained discovery objects."""

from __future__ import annotations

import json
import time

import paho.mqtt.client as mqtt

retained: dict[str, str] = {}


def on_connect(client, userdata, flags, rc):
    client.subscribe("homeassistant/#", qos=0)


def on_message(client, userdata, msg):
    if msg.retain and msg.payload:
        retained[msg.topic] = msg.payload.decode("utf-8", "replace")


client = mqtt.Client()
client.username_pw_set("hm", "abc123456")
client.on_connect = on_connect
client.on_message = on_message
client.connect("192.168.31.99", 1883, 30)
client.loop_start()
time.sleep(12)
client.loop_stop()
client.disconnect()

# inventory per serial
inventory: dict[str, set[str]] = {}
for topic, raw in retained.items():
    if not topic.endswith("/attributes"):
        continue
    try:
        data = json.loads(raw)
    except Exception:
        continue
    supported = data.get("supported_topics")
    if not isinstance(supported, dict):
        continue
    serial = topic.split("/")[2]
    inventory.setdefault(serial, set()).update(supported.keys())

# discovery objects per serial
objects: dict[str, set[str]] = {}
for topic in retained:
    parts = topic.split("/")
    if len(parts) < 5 or parts[0] != "homeassistant" or not topic.endswith("/config"):
        continue
    serial = parts[2]
    mid = parts[3] if len(parts) == 5 else "/".join(parts[3:-1])
    objects.setdefault(serial, set()).add(mid)

for serial in ("RMI-4161A0209FF6", "RMI-1650A028FC22", "RMI-4162A02ABFB5"):
    print(f"== {serial}")
    inv = inventory.get(serial, set())
    obj = objects.get(serial, set())
    print(f"   inventory ({len(inv)}): {', '.join(sorted(inv))}")
    print(f"   objects   ({len(obj)}): {', '.join(sorted(obj))}")
    print(f"   objects but NOT in inventory: {', '.join(sorted(obj - inv)) or '-'}")
    print(f"   inventory but no object:      {', '.join(sorted(inv - obj)) or '-'}")
    print()
