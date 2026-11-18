"""Which serials declare factory_reset / reset_ble_pin_code in supported_topics."""

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

print("serial                        factory_reset reset_ble  keys")
for topic, raw in sorted(retained.items()):
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
    print(
        f"  {serial:<28} {str('factory_reset' in supported):<13} "
        f"{str('reset_ble_pin_code' in supported):<10} {len(supported)}"
    )
