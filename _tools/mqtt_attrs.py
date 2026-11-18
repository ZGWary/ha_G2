"""Print supported_topics and entity_desc for every device that declares them."""

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

for topic in sorted(t for t in retained if t.endswith("/attributes")):
    dev = topic.split("/")[2]
    try:
        data = json.loads(retained[topic])
    except Exception:
        continue
    supported = sorted((data.get("supported_topics") or {}))
    desc = data.get("entity_desc") or {}
    print(f"=== {dev}")
    print(f"  supported_topics ({len(supported)}): {supported}")
    print(f"  entity_desc      ({len(desc)}): {sorted(desc)}")
    for key, value in sorted(desc.items()):
        print(f"      {key}: {value}")
    other = sorted(k for k in data if k not in ("supported_topics", "entity_desc"))
    if other:
        print(f"  other keys: {other}")
    print()
