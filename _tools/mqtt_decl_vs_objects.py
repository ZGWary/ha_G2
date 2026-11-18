"""Print the supported_topics declaration of every device, side by side."""

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
        print(f"{dev}: unparsable")
        continue
    supported = data.get("supported_topics") or {}
    objects = sorted(
        t.split("/")[3] if len(t.split("/")) == 5 else "/".join(t.split("/")[3:5])
        for t in retained
        if len(t.split("/")) > 3 and t.split("/")[2] == dev and t.endswith("/config")
    )
    print(f"=== {dev}")
    print(f"  declared topics ({len(supported)}): {sorted(supported)}")
    print(f"  discovery objects ({len(objects)}): {objects}")
    print()
