"""Print the declared supported_topics inventory for one serial."""

from __future__ import annotations

import json
import sys
import time

import paho.mqtt.client as mqtt

want = (sys.argv[1] if len(sys.argv) > 1 else "9FF6").upper()
retained: dict[str, str] = {}


def on_connect(client, userdata, flags, rc):
    client.subscribe("hoymiles/#", qos=0)
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

for topic, raw in sorted(retained.items()):
    if not topic.endswith("/attributes"):
        continue
    if want not in topic.upper():
        continue
    data = json.loads(raw)
    print(f"== {topic}")
    supported = data.get("supported_topics", {})
    print(f"   supported_topics ({len(supported)} keys):")
    for key, value in supported.items():
        print(f"     {key} = {value}")
    for key in data:
        if key == "supported_topics":
            continue
        value = data[key]
        text = json.dumps(value, ensure_ascii=False)
        print(f"   {key} = {text[:160]}")
